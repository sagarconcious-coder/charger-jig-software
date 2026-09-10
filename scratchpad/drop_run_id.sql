-- Drops the run_id column from both charger report tables.
-- Run this against the live DB (not covered by CREATE TABLE IF NOT EXISTS,
-- since those tables already exist). Safe to run once; re-running errors
-- harmlessly if the column is already gone.

ALTER TABLE `chargerReports` DROP COLUMN `run_id`;
ALTER TABLE `failedChargerReports` DROP COLUMN `run_id`;
