// Code-letter mappings for charger traceability serial numbers, per the
// "AEIDTH Traceability Detail" sheet (F.No. ADT_R&D_F003_V1.0).
//
// Mirrors the server's bms/charger_code_tables.py (aeidthocpp repo) so the
// Lot page's dropdowns render instantly instead of waiting on a network
// round trip to /api/charger-lot-options. These are fixed, rarely-changing
// choice lists (not per-lot data), so a local copy is safe - but it DOES
// mean the two copies can drift if the server table is ever edited without
// updating this file too. Lot *creation* still goes to the server (it needs
// an atomic, server-side sequence counter) - only the dropdown contents are
// mirrored here.
(function () {
  const VOLTAGE_AMP_CHOICES = [
    ["5825", "58V25A-5825"],
    ["7325", "73V25A-7325"],
  ];

  const VARIANT_CHOICES = [
    ["A", "CAN+IP-A"],
    ["B", "NON CAN+IP-B"],
  ];

  const CONNECTOR_CHOICES = [
    ["A", "Anderson SB75-A"],
    ["B", "Anderson SB50-B"],
    ["C", "Chagori-C"],
  ];

  const MS_ID_CHOICES = [
    ["A", "SHIGAN-A"],
    ["B", "SBT-B"],
    ["C", "OSRIM-C"],
    ["D", "TADASHI-D"],
    ["E", "IEMS-E"],
    ["G", "IKIO-G"],
  ];

  const MONTH_CHOICES = [
    ["A", "Jan"], ["B", "Feb"], ["C", "Mar"], ["D", "Apr"],
    ["E", "May"], ["F", "Jun"], ["G", "Jul"], ["H", "Aug"],
    ["I", "Sep"], ["J", "Oct"], ["K", "Nov"], ["L", "Dec"],
  ];
  const MONTH_CODES = MONTH_CHOICES.map(([c]) => c);

  const YEAR_CODE_BASE_YEAR = 2025; // "A" -> 2025, "B" -> 2026, ...

  const DEFAULT_VOLTAGE_AMP_CODE = "5825";
  const DEFAULT_VARIANT_CODE = "B";   // NON CAN+IP-B
  const DEFAULT_CONNECTOR_CODE = "A"; // Anderson SB75-A
  const DEFAULT_MS_ID_CODE = "G";     // IKIO-G

  function monthCodeFor(date) {
    return MONTH_CODES[date.getMonth()]; // 0-11 -> 'A'..'L'
  }

  function yearCodeFor(date) {
    const offset = date.getFullYear() - YEAR_CODE_BASE_YEAR;
    if (offset < 0 || offset > 25) {
      throw new Error(`Year ${date.getFullYear()} is out of the supported traceability code range`);
    }
    return String.fromCharCode("A".charCodeAt(0) + offset);
  }

  function toChoiceList(pairs) {
    return pairs.map(([code, label]) => ({ code, label }));
  }

  // Same shape as the server's charger_code_tables.options_payload(), so
  // lot.js can consume it identically regardless of source.
  function optionsPayload(now) {
    const date = now || new Date();
    return {
      voltage_amp: toChoiceList(VOLTAGE_AMP_CHOICES),
      variant: toChoiceList(VARIANT_CHOICES),
      connector: toChoiceList(CONNECTOR_CHOICES),
      ms_id: toChoiceList(MS_ID_CHOICES),
      month: toChoiceList(MONTH_CHOICES),
      year: [0, 1, 2, 3].map((i) => ({
        code: String.fromCharCode("A".charCodeAt(0) + i),
        label: String(YEAR_CODE_BASE_YEAR + i),
      })),
      defaults: {
        voltage_amp_code: DEFAULT_VOLTAGE_AMP_CODE,
        variant_code: DEFAULT_VARIANT_CODE,
        connector_code: DEFAULT_CONNECTOR_CODE,
        ms_id_code: DEFAULT_MS_ID_CODE,
        month_code: monthCodeFor(date),
        year_code: yearCodeFor(date),
      },
    };
  }

  window.ChargerCodeTables = { optionsPayload };
})();
