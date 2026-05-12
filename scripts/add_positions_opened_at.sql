-- Add optional purchase/open time on positions (hour-precision in app layer).
-- Run once per database if the column is missing.

-- PostgreSQL
-- ALTER TABLE positions ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ;

-- SQLite (no IF NOT EXISTS on ADD COLUMN in older builds; skip if already applied)
-- ALTER TABLE positions ADD COLUMN opened_at TIMESTAMP;
