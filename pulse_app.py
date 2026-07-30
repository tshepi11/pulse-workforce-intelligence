"""
PULSE Intelligence Engine
PowerFit Wellness Solutions (Pty) Ltd

Portfolio version - sanitised. Credentials, live URLs, and client data removed.

Single Flask endpoint that handles ALL inbound Turn.io (WhatsApp) messages:
  1. Categorised danger-word scanning with stem matching (4 crisis categories,
     multilingual: English, isiZulu, Afrikaans, Sesotho)
  2. Positive message detection and encouragement
  3. Crisis response via Turn.io API, matched to the situation
  4. Weekly check-in auto-pairing (wellbeing + energy -> burnout composite)
  5. Employee ID verification (EMP format -> SHA-256 -> SQLite lookup)
  6. Structured CSV logging feeding downstream workforce reporting

Endpoint: POST /webhook/pulse-main
"""

from flask import Flask, request, jsonify
import csv
import os
import sqlite3
import hashlib
import re
import requests
import json
from datetime import datetime

app = Flask(__name__)

# ---------------------------------------------------------------------------
# CONFIG - secrets are read from environment variables, never hard-coded
# ---------------------------------------------------------------------------
DB_PATH = "pulse_intelligence.db"
CSV_PATH = "pulse_data.csv"
PENDING_PATH = "pending_checkins.json"
TURN_TOKEN = os.environ.get("TURN_TOKEN", "")
TURN_API_URL = "https://whatsapp.turn.io/v1/messages"

# ---------------------------------------------------------------------------
# PENDING CHECK-IN STORAGE (file-based so it persists across restarts/workers)
# ---------------------------------------------------------------------------
def save_pending(phone, wellbeing_score, wellbeing_text):
    """Store a pending wellbeing score waiting for its energy score."""
    pending = load_all_pending()
    pending[phone] = {
        "wellbeing": wellbeing_score,
        "wellbeing_text": wellbeing_text,
        "timestamp": datetime.now().isoformat(),
    }
    with open(PENDING_PATH, "w") as f:
        json.dump(pending, f)


def get_pending(phone):
    """Retrieve and remove a pending wellbeing score for this phone."""
    pending = load_all_pending()
    if phone in pending:
        data = pending.pop(phone)
        with open(PENDING_PATH, "w") as f:
            json.dump(pending, f)
        return data
    return None


def load_all_pending():
    """Load all pending check-ins from file."""
    if os.path.exists(PENDING_PATH):
        try:
            with open(PENDING_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# ---------------------------------------------------------------------------
# DANGER WORD CATEGORIES
# Stems catch word families ("depress" -> depressed / depressing / depression).
# Phrases catch exact multi-word expressions, including local-language ones.
# ---------------------------------------------------------------------------
DANGER_CATEGORIES = {
    "WORKPLACE": {
        "stems": [
            "harass", "harrass",
            "bully", "bulli",
            "toxic",
            "hostile",
            "victimi",
            "intimidat",
            "raak",
            "dismiss",
            "suspend",
            "discriminat",
            "unfair",
            "threaten",
        ],
        "phrases": [
            "fired me",
            "baas raak",
            "wrote me up",
            "final warning",
            "my manager",
            "my supervisor",
            "my boss",
        ],
        "response": (
            "Hey. It takes a lot of courage to just stop, look at what's happening "
            "to you, and finally say, \"This isn't right.\" Just admitting that to "
            "yourself is a huge step, and you should be proud of that.\n\n"
            "What is happening to you at work is wrong. You do not have to carry "
            "this heavy load or try to fix it all by yourself.\n\n"
            "If you feel safe at work: Try talking to just one person you trust. "
            "A coworker, a different boss, or your union rep. Sometimes, telling "
            "just one person can change everything.\n\n"
            "If you don't feel safe talking to anyone at work: That is completely "
            "okay. You still have people on your side who can help you.\n\n"
            "CCMA Helpline: 011 377 6650\n"
            "Department of Labour: 0800 030 007 (this call is free)\n\n"
            "You stood up for yourself today just by facing this. That really "
            "matters. Take it one day at a time. \U0001F499"
        ),
    },
    "GBV": {
        "stems": [
            "abus",
            "rape",
            "molest",
            "beat",
            "controllin",
            "stalk",
        ],
        "phrases": [
            "hit me", "hits me", "hitting me",
            "gbv",
            "scared of him", "scared of her",
            "hurt me", "hurts me", "hurting me",
            "my boyfriend", "my partner", "my husband",
            "he chokes", "he choked",
            "locked me",
            "won't let me leave",
            "protection order",
        ],
        "response": (
            "We hear you. And we want you to know that what you just did takes "
            "more courage than most people will ever understand.\n\n"
            "You don't deserve what's happening to you. And you don't have to "
            "carry it alone.\n\n"
            "These lines are free, confidential, and available right now:\n\n"
            "GBV Command Centre: 0800 428 428 (24/7, free)\n"
            "People Opposing Women Abuse: 011 642 4345\n"
            "Lifeline: 0861 322 322\n\n"
            "No one will judge you. No one will rush you. You call when "
            "you're ready.\n\n"
            "This stays between us. \U0001F499"
        ),
    },
    "MENTAL_HEALTH": {
        "stems": [
            "suicid",
            "depress",
            "hopeless",
            "worthless",
            "self-harm", "selfharm",
        ],
        "phrases": [
            "kill myself",
            "ngifuna ukufa",
            "Ek wil net slaap en nie wakker word nie",
            "end it all",
            "end my life",
            "don't want to live", "dont want to live",
            "wanna die", "want to die",
            "can't do this anymore", "cant do this anymore", "cant do this",
            "can't go on", "cant go on",
            "give up",
            "hurting myself",
            "hurt myself",
            "no reason to live",
            "better off without me",
            "nobody cares",
            "i'm done", "im done",
        ],
        "response": (
            "Hey. We are so glad you said something. Seriously.\n\n"
            "Whatever you are carrying right now is so heavy. And the fact that "
            "you are still here, still showing up, and still typing this message? "
            "That is strength. Even if it doesn't feel like it.\n\n"
            "Please talk to someone today. Not tomorrow. Today.\n\n"
            "SADAG: 0800 567 567 (24/7, free)\n"
            "Lifeline: 0861 322 322\n"
            "SMS helpline: 31393 (free)\n\n"
            "You don't have to explain everything. You just have to say "
            "'I need help.' They'll take it from there.\n\n"
            "We're here. And this stays between us. \U0001F499"
        ),
    },
    "FINANCIAL": {
        "stems": [
            "evict",
            "garnish",
            "mashonisa",
            "starv",
        ],
        "phrases": [
            "can't feed", "cant feed",
            "no money",
            "no food",
            "lapile",
            "no taxi money", "transport money",
            "don't have food",
            "hungry",
            "can't afford", "cant afford",
            "loan shark",
            "no electricity",
            "debt review",
            "can't pay", "cant pay",
            "feed my children", "feed my kids", "feed my family",
            "going without",
        ],
        "response": (
            "Hey. We hear you. And we are not going to pretend that a message "
            "fixes what you are going through right now.\n\n"
            "But you spoke up, and that takes real guts. Asking for help to take "
            "care of the people you love is not a weakness. That is love.\n\n"
            "These places are completely free, and they will keep your "
            "information secret:\n\n"
            "National Debt Mediation: 0861 111 336 (to help with debt and money stress)\n"
            "Legal Aid SA: 0800 110 110 (free legal help if you are facing "
            "eviction or legal trouble)\n"
            "SASSA Helpline: 0800 601 011 (for grant info)\n"
            "Social Relief of Distress: Visit your nearest DSD office for "
            "urgent food or grant help\n\n"
            "If you or your children are going without food today, please reach "
            "out to your HR team. You do not have to explain everything, just "
            "tell them you need support.\n\n"
            "You are not failing. You are fighting. There is a big difference. \U0001F499"
        ),
    },
}

# ---------------------------------------------------------------------------
# POSITIVE WORD DETECTION
# ---------------------------------------------------------------------------
POSITIVE_STEMS = [
    "grateful", "thankful", "blessed",
    "proud", "amazing", "awesome",
    "fantastic", "wonderful",
]

POSITIVE_PHRASES = [
    "great job", "well done", "good day", "great day", "good", "great",
    "feeling good", "feel good", "feeling great", "feel great",
    "feeling happy", "feel happy",
    "love my job", "love my life",
    "thank god", "thank the lord",
    "on top of the world",
    "best day",
]

POSITIVE_RESPONSE = (
    "That's what we love to hear! \U0001F499\n\n"
    "Hold onto this feeling. You earned it. Life can be a roller coaster "
    "with plenty of ups and downs.\n\nSo celebrate the ups and when those down days do come around, "
    "just remember this moment right here. Remember how good it feels to "
    "feel good, and know that you will get back to this place again.\n\n"
    "This feeling today? It's a big deal.\n\n"
    "Keep going. We're right here with you every week."
)

# ---------------------------------------------------------------------------
# BURNOUT SCORING
# Wellbeing (3/2/1) + Energy (2/1) pair into a composite out of 5.
# Local-language button labels are scored the same as English ones.
# ---------------------------------------------------------------------------
WELLBEING_MAP = {
    "excellent": 3, "m'jojo": 3, "mjojo": 3,
    "managing": 2, "ai sana": 2,
    "need support": 1,
}

ENERGY_MAP = {
    "energised": 2, "ke fresh": 2,
    "tired": 1, "moeg": 1,
}

BURNOUT_LABELS = {
    5: "GREEN",
    4: "AMBER_LOW",
    3: "AMBER_HIGH",
    2: "CRITICAL",
}

EMP_PATTERN = re.compile(r"^EMP\d+$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def strip_emoji(text):
    """Remove emoji characters from text for clean CSV logging."""
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
        "\U00002600-\U000026FF\U00002700-\U000027BF]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text).strip()


def ensure_csv_header():
    """Create pulse_data.csv with a header row if it doesn't exist yet."""
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "timestamp", "phone_number", "emp_id",
                "status", "danger_category", "flagged_word",
                "wellbeing_score", "energy_score", "burnout_composite",
                "message"
            ])


def log_to_csv(phone, emp_id, status, danger_category, flagged_word,
               wellbeing_score, energy_score, burnout_composite, message):
    """Append one structured row to pulse_data.csv."""
    ensure_csv_header()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(timespec="seconds"),
            phone,
            emp_id,
            status,
            danger_category or "",
            flagged_word or "",
            wellbeing_score or "",
            energy_score or "",
            burnout_composite or "",
            strip_emoji(message),
        ])


def scan_for_danger(text):
    """Scan text against all danger categories. Phrases first, then stems."""
    text_lower = text.lower()
    for category, config in DANGER_CATEGORIES.items():
        for phrase in config.get("phrases", []):
            if phrase in text_lower:
                return category, phrase, config["response"]
    for category, config in DANGER_CATEGORIES.items():
        for stem in config.get("stems", []):
            if re.search(rf"\b{re.escape(stem)}\w*", text_lower):
                return category, stem, config["response"]
    return None, None, None


def scan_for_positive(text):
    """Scan text for positive language."""
    text_lower = text.lower()
    for phrase in POSITIVE_PHRASES:
        if phrase in text_lower:
            return phrase, POSITIVE_RESPONSE
    for stem in POSITIVE_STEMS:
        if re.search(rf"\b{re.escape(stem)}\w*", text_lower):
            return stem, POSITIVE_RESPONSE
    return None, None


def score_wellbeing(text):
    """Convert wellbeing button text to a numeric score (3/2/1) or None."""
    text_lower = text.lower()
    for key, score in WELLBEING_MAP.items():
        if key in text_lower:
            return score
    return None


def score_energy(text):
    """Convert energy button text to a numeric score (2/1) or None."""
    text_lower = text.lower()
    for key, score in ENERGY_MAP.items():
        if key in text_lower:
            return score
    return None


def get_emp_id_by_phone(phone):
    """Look up an employee's staff_id using their linked phone number.

    Parameterised query (?) - user input is never concatenated into SQL.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT staff_id FROM corporate_roster WHERE phone_number = ?",
            (phone,),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def verify_emp_id(emp_text, phone):
    """Hash the Employee ID with SHA-256 and look it up in the roster.

    Raw employee IDs are never stored - only their hashes (privacy by design).
    """
    hashed = hashlib.sha256(emp_text.upper().encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT staff_id FROM corporate_roster WHERE hashed_staff_id = ?",
            (hashed,),
        )
        row = cursor.fetchone()
        if row:
            staff_id = row[0]
            cursor.execute(
                "UPDATE corporate_roster SET phone_number = ? WHERE staff_id = ?",
                (phone, staff_id),
            )
            conn.commit()
            return True, staff_id
        return False, None
    finally:
        conn.close()


def send_response(phone, response_text, label):
    """Send a response via the Turn.io API."""
    headers = {
        "Authorization": f"Bearer {TURN_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "to": phone,
        "type": "text",
        "text": {
            "body": response_text
        },
    }
    try:
        resp = requests.post(TURN_API_URL, json=body, headers=headers)
        print(f"\U0001F4E8 {label} response sent | Status: {resp.status_code}")
    except Exception as e:
        print(f"\u26A0\uFE0F Failed to send {label} response: {e}")


def extract_message(payload):
    """Pull the message text, phone number, and source from a Turn.io webhook payload.

    Handles plain text, button replies, and list replies, plus a fallback
    shape for non-Turn payloads.
    """
    messages = payload.get("messages") or []
    if messages:
        msg = messages[0]
        text = (msg.get("text") or {}).get("body", "")
        if not text:
            interactive = msg.get("interactive") or {}
            button = interactive.get("button_reply") or {}
            text = button.get("title", "")
            if not text:
                list_reply = interactive.get("list_reply") or {}
                text = list_reply.get("title", "")
        phone = msg.get("from", "")
        return text.strip(), phone.strip(), None

    text = payload.get("text") or payload.get("message") or payload.get("body") or ""
    phone = (
        payload.get("from")
        or payload.get("phone")
        or payload.get("msisdn")
        or ""
    )
    source = payload.get("source") or None
    return str(text).strip(), str(phone).strip(), source


# ---------------------------------------------------------------------------
# MASTER ENDPOINT
# ---------------------------------------------------------------------------
@app.route("/webhook/pulse-main", methods=["POST"])
def pulse_main():
    payload = request.get_json(silent=True) or {}
    user_text, phone, source = extract_message(payload)

    if not user_text:
        return jsonify({"status": "no_text"}), 200

    # --- STEP 1: Always scan for danger words first ---
    danger_category, flagged_word, crisis_response_text = scan_for_danger(user_text)

    # --- STEP 2: Check if it's an EMP ID ---
    verified = False
    staff_id = None
    if EMP_PATTERN.match(user_text):
        verified, staff_id = verify_emp_id(user_text, phone)

    # --- STEP 3: Check for positive language ---
    positive_word, positive_response_text = scan_for_positive(user_text)

    # --- STEP 4: Check if it's a wellbeing or energy button tap ---
    wellbeing_score = score_wellbeing(user_text)
    energy_score = score_energy(user_text)

    # --- STEP 5: Auto-pair check-in scores ---
    burnout_composite = None
    burnout_label = None

    if wellbeing_score:
        # First button tap - store it and wait for the energy tap
        save_pending(phone, wellbeing_score, strip_emoji(user_text))
        w_label = {3: "Excellent", 2: "Managing", 1: "Need support"}.get(wellbeing_score, "?")
        print(f"\U0001F4CA CHECKIN (waiting for energy) | Wellbeing: {w_label} ({wellbeing_score})")
        # Don't log yet - wait for the energy tap to complete the pair
        return jsonify({"status": "pending", "wellbeing_score": wellbeing_score}), 200

    if energy_score:
        # Check if we have a pending wellbeing score for this phone
        pending = get_pending(phone)
        if pending:
            wellbeing_score = pending["wellbeing"]
            burnout_composite = wellbeing_score + energy_score
            burnout_label = BURNOUT_LABELS.get(burnout_composite, "UNKNOWN")

    # --- STEP 6: Determine final status ---
    if flagged_word:
        status = "RED_FLAG"
        print(f"\U0001F6A8 RED FLAG: {danger_category} | word: '{flagged_word}'")
        send_response(phone, crisis_response_text, danger_category)

    elif energy_score and burnout_label:
        # Complete check-in - both scores paired
        status = f"CHECKIN_{burnout_label}"
        print(f"\U0001F4CA BURNOUT: {burnout_label} | Score: {burnout_composite}/5")

    elif energy_score and not burnout_label:
        # Energy tap without a pending wellbeing - log as standalone
        status = "ENERGY_ONLY"

    elif verified:
        status = "VERIFIED"

    elif EMP_PATTERN.match(user_text) and not verified:
        status = "ID_FAILED"

    elif source == "onboarding":
        status = "ID_FAILED"

    elif positive_word:
        status = "POSITIVE"
        send_response(phone, positive_response_text, "POSITIVE")

    else:
        status = "NORMAL"

    # --- STEP 7: Look up employee ID for logging ---
    emp_id = staff_id if staff_id else get_emp_id_by_phone(phone)

    # --- STEP 8: Log to CSV ---
    log_to_csv(
        phone, emp_id, status, danger_category, flagged_word,
        wellbeing_score, energy_score, burnout_composite,
        user_text
    )

    # --- STEP 9: Return JSON ---
    return jsonify({
        "status": status,
        "verified": verified,
        "staff_id": staff_id,
        "flagged_word": flagged_word,
        "danger_category": danger_category,
        "wellbeing_score": wellbeing_score,
        "energy_score": energy_score,
        "burnout_composite": burnout_composite,
        "burnout_label": burnout_label,
    }), 200


# ---------------------------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ensure_csv_header()
    print("=" * 50)
    print("  PULSE Intelligence Engine \u2014 Running")
    print("  Endpoint: POST /webhook/pulse-main")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000)
