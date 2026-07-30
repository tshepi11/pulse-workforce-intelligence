# PULSE: Workforce Intelligence Engine

A production system I designed and built solo for PowerFit Wellness Solutions:
it delivers wellness engagement to employees over WhatsApp and converts their
interaction data into real-time workforce risk intelligence for HR leadership.

The strategic idea: reach the employees who never raise their hand - especially
deskless workers with no company email - and turn unstructured conversation
data into structured, board-ready risk indicators.

## Architecture

```
Client roster (CSV)
        │  ingestion: onboard\\\_client.py - IDs hashed with SHA-256 at load
        ▼
SQLite roster (no raw-ID storage in the verification path)

Turn.io (WhatsApp API)
        │  webhook (JSON)
        ▼
Flask app (Python) - deployed on PythonAnywhere
        │
        ├── Risk Engine - scans every message against 4 crisis categories
        │   (workplace, GBV, mental health, financial) using phrase and
        │   word-stem matching in English, isiZulu, Afrikaans, and Sesotho,
        │   and sends a matched crisis response with real SA helplines
        │
        ├── Check-in pipeline - pairs wellbeing + energy button taps into
        │   a burnout composite score (GREEN / AMBER / CRITICAL), with
        │   pending state persisted to disk so it survives restarts
        │
        ├── Identity layer - employee IDs verified via SHA-256 hash lookup
        │   in SQLite; verification never compares raw IDs
        │
        ▼
Structured event log (timestamped, cleaned, categorised)
        │
        ▼
Quarterly Power Pulse workforce reports for client HR teams
```

## What's in this repo

|File|What it is|
|-|-|
|`pulse\\\_app.py`|The full intelligence engine: webhook handling, multilingual risk scanning, burnout scoring, ID verification, structured logging|
|`queries.sql`|The roster queries used live in the app, plus the reporting queries behind the quarterly workforce reports|
|`onboard\\\_client.py`|Client ingestion script: reads a new client's employee roster from CSV, SHA-256 hashes each ID, and loads it into the database - the same hashing the app uses at verification, so matches always work|
|`data_flow` |end-to-end data flow, source-to-target mapping, data dictionary with sensitivity classification, access controls, and known gaps with roadmap|

## Engineering decisions worth noting

* **Safety first in the pipeline**: every inbound message is scanned for
crisis language before any other processing.
* **Privacy by design**: verification runs against SHA-256 hashes, never raw IDs, in line with POPIA thinking.
Making the hash the sole stored identifier is the next hardening step.
* **Parameterised SQL throughout** - no string concatenation, no injection risk.
* **Durable state**: pending check-ins are written to disk, not held in
memory, so a restart never loses half a check-in.
* **Secrets in environment variables**, never in code.

## Notes

This is a sanitised portfolio version: credentials, live URLs, and all
client/employee data have been removed.

