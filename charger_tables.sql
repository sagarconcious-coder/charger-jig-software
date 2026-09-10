-- Charger Lot / Serial / Report tables (PASS side) + Failed Charger tables
-- (FAIL side, fully separate - no lot, own "FAIL%06d" serial counter, own
-- "FAILRPT%06d" report counter, never touches the PASS-side tables/counters).
-- MySQL (matches settings/__init__.py DATABASES['default'] ENGINE=mysql)
-- Mirrors bms/models.py: ChargerLot, ChargerSerialSeqCounter,
-- ChargerSerialNumber, ChargerReportSeqCounter, ChargerReport,
-- FailedChargerSerialNumber, FailedChargerReport
-- (includes dut_firmware_version / dut_hardware_version on both report tables)

CREATE TABLE IF NOT EXISTS `chargerLots` (
  `id`               INT AUTO_INCREMENT PRIMARY KEY,
  `lot_code`         INT UNSIGNED NOT NULL,
  `voltage_amp_code` VARCHAR(8)  NOT NULL,
  `variant_code`     VARCHAR(1)  NOT NULL,
  `connector_code`   VARCHAR(1)  NOT NULL,
  `ms_id_code`       VARCHAR(1)  NOT NULL,
  `month_code`       VARCHAR(1)  NOT NULL,
  `year_code`        VARCHAR(1)  NOT NULL,
  `prefix`           VARCHAR(16) NOT NULL,
  -- No longer used to generate serials (kept only to avoid a migration -
  -- see ChargerSerialSeqCounter below, which is the actual global counter).
  `next_seq`         INT UNSIGNED NOT NULL DEFAULT 1,
  `created_at`       DATETIME(6) NOT NULL,
  `created_by`       VARCHAR(64) NULL,
  CONSTRAINT `uniq_lot_code_per_month` UNIQUE (`year_code`, `month_code`, `lot_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Single-row table holding the next serial seq to hand out, SHARED across
-- every lot - the running 5-digit part of the serial number is one
-- continuous sequence regardless of which lot a unit belongs to. id is
-- always 1.
CREATE TABLE IF NOT EXISTS `chargerSerialSeqCounter` (
  `id`       INT AUTO_INCREMENT PRIMARY KEY,
  `next_seq` INT UNSIGNED NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Single-row table holding the next report_seq to hand out, shared between
-- chargerReports and failedChargerReports so "Report No." reflects true
-- submission order across both PASS and FAIL. id is always 1.
CREATE TABLE IF NOT EXISTS `chargerReportSeqCounter` (
  `id`       INT AUTO_INCREMENT PRIMARY KEY,
  `next_seq` INT UNSIGNED NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `chargerSerialNumbers` (
  `serial_number` VARCHAR(32) NOT NULL PRIMARY KEY,
  `lot_id`        INT NOT NULL,
  `seq`           INT UNSIGNED NOT NULL,
  `created_at`    DATETIME(6) NOT NULL,
  KEY `chargerSerialNumbers_lot_id_idx` (`lot_id`),
  CONSTRAINT `fk_chargerSerialNumbers_lot`
    FOREIGN KEY (`lot_id`) REFERENCES `chargerLots` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `chargerReports` (
  `serial_number`        VARCHAR(32) NOT NULL PRIMARY KEY,
  `lot_id`                INT NOT NULL,
  `start_time`            DATETIME(6) NULL,
  `end_time`              DATETIME(6) NULL,
  `overall_result`        BOOL NULL,
  `jig_firmware_version`  VARCHAR(16) NULL,
  `jig_hardware_version`  VARCHAR(16) NULL,
  `dut_firmware_version`  VARCHAR(16) NULL,
  `dut_hardware_version`  VARCHAR(16) NULL,
  `qr_values`              JSON NOT NULL,
  `parameters`             JSON NOT NULL,
  `created_by`            VARCHAR(64) NULL,
  `created_at`            DATETIME(6) NOT NULL,
  KEY `chargerReports_lot_id_idx` (`lot_id`),
  CONSTRAINT `fk_chargerReports_serial`
    FOREIGN KEY (`serial_number`) REFERENCES `chargerSerialNumbers` (`serial_number`) ON DELETE RESTRICT,
  CONSTRAINT `fk_chargerReports_lot`
    FOREIGN KEY (`lot_id`) REFERENCES `chargerLots` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── FAIL side (independent of everything above) ─────────────────────────

CREATE TABLE IF NOT EXISTS `failedChargerSerialNumbers` (
  `serial_number` VARCHAR(32) NOT NULL PRIMARY KEY,
  `seq`           INT UNSIGNED NOT NULL UNIQUE,
  `created_at`    DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `failedChargerReports` (
  `serial_number`        VARCHAR(32) NOT NULL PRIMARY KEY,
  `report_seq`            INT NOT NULL AUTO_INCREMENT UNIQUE,
  `start_time`            DATETIME(6) NULL,
  `end_time`              DATETIME(6) NULL,
  `overall_result`        TINYINT(1) NULL,
  `jig_firmware_version`  VARCHAR(16) NULL,
  `jig_hardware_version`  VARCHAR(16) NULL,
  `dut_firmware_version`  VARCHAR(16) NULL,
  `dut_hardware_version`  VARCHAR(16) NULL,
  `qr_values`              JSON NOT NULL,
  `parameters`             JSON NOT NULL,
  `created_by`            VARCHAR(64) NULL,
  `created_at`            DATETIME(6) NOT NULL,
  CONSTRAINT `fk_failedChargerReports_serial`
    FOREIGN KEY (`serial_number`) REFERENCES `failedChargerSerialNumbers` (`serial_number`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
