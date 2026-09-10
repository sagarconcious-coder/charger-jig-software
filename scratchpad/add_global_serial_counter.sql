-- Adds the global serial sequence counter table, shared across all lots.
-- Run this against the live DB before deploying the updated bms code -
-- ChargerSerialNumberView now reads/writes this table instead of each
-- lot's own next_seq.
--
-- Seeds next_seq to continue from the HIGHEST next_seq currently sitting on
-- any existing chargerLots row, so serial numbers keep climbing rather than
-- restarting at 1 and potentially colliding with serials already issued to
-- some lot. Adjust the seed manually first if you want a different starting
-- point.

CREATE TABLE IF NOT EXISTS `chargerSerialSeqCounter` (
  `id`       INT AUTO_INCREMENT PRIMARY KEY,
  `next_seq` INT UNSIGNED NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO `chargerSerialSeqCounter` (`id`, `next_seq`)
SELECT 1, COALESCE(MAX(`next_seq`), 1) FROM `chargerLots`
ON DUPLICATE KEY UPDATE `next_seq` = VALUES(`next_seq`);
