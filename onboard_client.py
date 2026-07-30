"""
PULSE: New Client Onboarding Script
====================================
Loads a client's employee roster into pulse_intelligence.db.

HOW TO USE (the whole runbook):
  1. Get the client's employee numbers as a CSV file with one
     column named: employee_number
  2. Put that CSV in the same folder as this script and the .db file
  3. Run:   python onboard_client.py client_abc.csv
  4. Upload the updated pulse_intelligence.db to PythonAnywhere
     (Files tab), replacing the old one
  5. Reload the web app on PythonAnywhere (Web tab -> Reload)

That's it! Employees can now scan the QR and verify.
"""

import csv
import hashlib
import sqlite3
import sys

DB_PATH = "pulse_intelligence.db"


def onboard(csv_path):
    # --- 1. Read the client's employee numbers from their CSV ---
    employee_numbers = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            emp = (row.get("employee_number") or "").strip().upper()
            if emp:
                employee_numbers.append(emp)

    if not employee_numbers:
        print("No employee numbers found - check the CSV has a column "
              "called 'employee_number'.")
        return

    # --- 2. Connect and make sure the table exists ---
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS corporate_roster (
            staff_id TEXT PRIMARY KEY,
            hashed_staff_id TEXT,
            phone_number TEXT
        )
    """)

    # --- 3. Hash and insert each employee ---
    # .upper() matters: app.py upper-cases what employees type before
    # hashing, so we must hash the same way here or matches will fail.
    added, skipped = 0, 0
    for emp in employee_numbers:
        hashed = hashlib.sha256(emp.encode()).hexdigest()
        try:
            cur.execute(
                "INSERT INTO corporate_roster "
                "(staff_id, hashed_staff_id, phone_number) VALUES (?, ?, ?)",
                (emp, hashed, None),
            )
            added += 1
        except sqlite3.IntegrityError:
            # Already in the roster (staff_id is the primary key) - skip
            skipped += 1

    conn.commit()
    conn.close()

    print(f"Done. Added {added} employees, skipped {skipped} already-loaded.")
    print("Next: upload pulse_intelligence.db to PythonAnywhere and "
          "reload the web app.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python onboard_client.py <client_roster.csv>")
    else:
        onboard(sys.argv[1])
