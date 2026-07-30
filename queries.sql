-- ===========================================================================
-- PULSE Intelligence Engine - SQL
-- SQLite database: pulse_intelligence.db
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. ROSTER QUERIES (used live inside the Flask app)
-- All queries are parameterised (?) - user input is never concatenated
-- into SQL strings, which protects against SQL injection.
-- ---------------------------------------------------------------------------

-- Look up an employee ID from a linked phone number (used when logging)
SELECT staff_id
FROM corporate_roster
WHERE phone_number = ?;

-- Verify an employee: the ID they typed is SHA-256 hashed in Python,
-- then matched against the stored hash. Raw IDs are never stored.
SELECT staff_id
FROM corporate_roster
WHERE hashed_staff_id = ?;

-- After successful verification, link the phone number to the employee
UPDATE corporate_roster
SET phone_number = ?
WHERE staff_id = ?;

-- ---------------------------------------------------------------------------
-- 2. REPORTING QUERIES (interaction data loaded into a pulse_events table
--    for the quarterly Power Pulse workforce reports)
-- ---------------------------------------------------------------------------

-- Red flags per crisis category: which risks are showing up, and how often
SELECT danger_category,
       COUNT(*) AS flag_count
FROM pulse_events
WHERE status = 'RED_FLAG'
GROUP BY danger_category
ORDER BY flag_count DESC;

-- Burnout distribution: how many completed check-ins landed in each band
SELECT status,
       COUNT(*) AS checkin_count
FROM pulse_events
WHERE status LIKE 'CHECKIN_%'
GROUP BY status
ORDER BY checkin_count DESC;

-- Monthly trend of red flags: is workforce risk rising or falling over time
SELECT strftime('%Y-%m', timestamp) AS month,
       COUNT(*) AS red_flags
FROM pulse_events
WHERE status = 'RED_FLAG'
GROUP BY strftime('%Y-%m', timestamp)
ORDER BY month;

-- Average burnout score per month (higher = healthier, max 5)
SELECT strftime('%Y-%m', timestamp) AS month,
       ROUND(AVG(burnout_composite), 2) AS avg_burnout_score,
       COUNT(*) AS completed_checkins
FROM pulse_events
WHERE burnout_composite IS NOT NULL
GROUP BY strftime('%Y-%m', timestamp)
ORDER BY month;

-- Engagement overview: how many messages of each type came in
SELECT status,
       COUNT(*) AS messages
FROM pulse_events
GROUP BY status
ORDER BY messages DESC;
