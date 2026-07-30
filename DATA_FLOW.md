# PULSE: Data Flow, Mapping \& Dictionary

Documentation of how data moves through PULSE: where it originates, how it is
transformed, where it rests, who can see it, and what each field means.

\---

## 1\. Data flow

```
STAGE 1 - SOURCE
  Client HR system  ──▶  employee roster (CSV)          \[one-off, per client]
  Employee's phone  ──▶  WhatsApp message               \[continuous]

STAGE 2 - INGESTION
  Roster:   onboard\_client.py - normalise (trim, upper-case), SHA-256 hash,
            insert into corporate\_roster
  Messages: Turn.io webhook (JSON, HTTPS) ──▶ Flask endpoint /webhook/pulse-main

STAGE 3 - TRANSFORMATION  (in-app, per message)
  a. Parse       - extract text, phone, source from the webhook payload
  b. Risk scan   - phrase + word-stem match across 4 crisis categories,
                   4 languages  →  danger\_category, flagged\_word
  c. Verify      - hash typed ID, match against roster  →  staff\_id link
  d. Score       - wellbeing (3/2/1) parked to disk, paired with energy (2/1)
                   →  burnout\_composite (2–5)  →  band label
  e. Classify    - assign status (RED\_FLAG / CHECKIN\_\* / VERIFIED / POSITIVE /
                   NORMAL / ID\_FAILED)
  f. Clean       - strip emoji for analytical consistency

STAGE 4 - STORAGE
  corporate\_roster (SQLite)     - identity and phone linkage
  pending\_checkins.json (disk)  - transient state, deleted once paired
  pulse\_data.csv                - structured event log, append-only

STAGE 5 - CONSUMPTION
  Aggregate queries (queries.sql)  ──▶  quarterly Power Pulse workforce report
  No individual-level output leaves the system.
```

\---

## 2\. Source-to-target mapping

### Roster ingestion - client CSV → `corporate\_roster`

|Source field|Transformation|Target field|Notes|
|-|-|-|-|
|`employee\_number`|trim whitespace, upper-case|`staff\_id`|Primary key; format varies by client|
|`employee\_number`|trim, upper-case, SHA-256|`hashed\_staff\_id`|Verification key - must use identical normalisation to the app, or matches fail|
|*(none at load)*|populated at verification|`phone\_number`|Empty until the employee onboards|

### Message ingestion - Turn.io payload → event log

|Source (webhook JSON)|Transformation|Target field|
|-|-|-|
|*(system clock)*|ISO-8601, second precision|`timestamp`|
|`messages\[0].from`|trim|`phone\_number`|
|*(roster lookup by phone)*|SELECT on `corporate\_roster`|`emp\_id`|
|*(derived)*|funnel classification|`status`|
|`messages\[0].text.body`|phrase then stem match|`danger\_category`, `flagged\_word`|
|`interactive.button\_reply.title`|map label → 3/2/1|`wellbeing\_score`|
|`interactive.button\_reply.title`|map label → 2/1|`energy\_score`|
|*(derived)*|wellbeing + energy|`burnout\_composite`|
|`messages\[0].text.body`|strip emoji|`message`|

Note: button replies and list replies arrive in different parts of the payload
than free text, so the parser checks all three shapes before giving up.

\---

## 3\. Data dictionary

### `corporate\_roster`

|Field|Type|Meaning|Sensitivity|
|-|-|-|-|
|`staff\_id`|TEXT (PK)|Employee number as supplied by the client|Identifying - hash-only storage is the next hardening step|
|`hashed\_staff\_id`|TEXT|SHA-256 of the normalised employee number; what verification matches against|Non-reversible|
|`phone\_number`|TEXT|WhatsApp number linked at verification|Personal data|

### Event log (`pulse\_data.csv`)

|Field|Type|Meaning|Sensitivity|
|-|-|-|-|
|`timestamp`|ISO-8601|When the message was processed|Low|
|`phone\_number`|TEXT|Sender's WhatsApp number|Personal data|
|`emp\_id`|TEXT|Linked employee, or `UNKNOWN` if unverified|Identifying|
|`status`|TEXT|Funnel outcome for this message|Low|
|`danger\_category`|TEXT|`WORKPLACE` / `GBV` / `MENTAL\_HEALTH` / `FINANCIAL`, or blank|Highly sensitive|
|`flagged\_word`|TEXT|Which phrase or stem triggered the flag - kept for tuning false positives|Sensitive|
|`wellbeing\_score`|INT|3 excellent, 2 managing, 1 needs support|Sensitive|
|`energy\_score`|INT|2 energised, 1 tired|Sensitive|
|`burnout\_composite`|INT|Wellbeing + energy, 2–5|Sensitive|
|`message`|TEXT|Message body, emoji stripped|Highly sensitive|

### Derived measure: burnout composite

|Score|Band|Reading|
|-|-|-|
|5|GREEN|Coping and energised|
|4|AMBER\_LOW|Early strain|
|3|AMBER\_HIGH|Sustained strain|
|2|CRITICAL|Needs support, depleted|

Check-in wording is held constant week to week so the measure stays comparable
over time - a trend line needs the same ruler every time.

\---

## 4\. Access controls

|Layer|Who / what|Access|
|-|-|-|
|Client HR|Aggregate reports only|No individual records, ever|
|Employee|Their own WhatsApp thread|No system access|
|Platform owner|Full database and logs|Single administrator, credentialed login|
|Application|Roster + event log|Parameterised queries only; secrets from environment variables|
|Transport|Turn.io → app|HTTPS|

Crisis responses go directly to the employee. A red flag raises no individual
alert to the employer - the employer sees only category counts in aggregate.

\---

## 5\. Known gaps and roadmap

|Gap|Planned change|
|-|-|
|Raw employee ID stored alongside its hash|Make the hash the sole stored identifier|
|No encryption at rest|Encrypt the database file and backups|
|Multi-client ID collision risk|Hash company code + employee number together; separate Turn.io channel per client already isolates inbound traffic|
|Event log in CSV|Move into the database as a proper `pulse\_events` table|
|Keyword matching misses meaning|Add a language-model classifier alongside the keyword pass|
|No automated tests|Unit tests for each funnel path; integration tests against sample payloads|
|Single-server deployment|Managed cloud: API gateway + serverless function, object storage for raw intake, managed database for structured output|



