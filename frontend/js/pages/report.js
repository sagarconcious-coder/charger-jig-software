(function () {
  // CR-05/4.6: identification fields on the report page. Array-driven so
  // more QR fields can be appended later without touching render logic.
  const QR_FIELDS = [{ key: "qr_code_1", label: "QR Code" }];

  let run = null;

  function fmt(v, digits = 3) {
    return v === null || v === undefined ? "--" : Number(v).toFixed(digits);
  }

  function timeStr(ts) {
    if (!ts) return "--";
    return new Date(ts * 1000).toLocaleString(undefined, { hour12: false });
  }

  function render() {
    const root = document.getElementById("page-report");
    if (!run) {
      root.innerHTML = `
        <div class="page-header">
          <div><h1>Test Report</h1><div class="page-sub">No locked test result yet</div></div>
        </div>
        <div class="empty-state">Lock a test from the Dashboard to open its report.</div>
      `;
      return;
    }

    const overallPass = run.overall_pass;
    const resultText = overallPass ? "PASS" : overallPass === false ? "FAIL" : "PENDING";
    const resultColor = overallPass ? "#4ade80" : overallPass === false ? "#ff8a8a" : "var(--text-muted)";

    root.innerHTML = `
      <div class="page-header">
        <div><h1>Test Report</h1><div class="page-sub">Run ${run.run_id} &middot; ${timeStr(run.start_time)}</div></div>
        <button class="btn btn-ghost btn-sm" id="reportBackBtn">${icon("dashboard", 13)} Back to Dashboard</button>
      </div>

      <div class="grid-2" style="margin-bottom:16px;">
        <div class="card card-pad">
          <h3 style="margin:0 0 12px;font-size:13px;">IDENTIFICATION</h3>
          <div class="field">
            <label>Charger Part Number</label>
            <input type="text" id="reportPartNumber" placeholder="Enter part number" />
          </div>
          ${QR_FIELDS.map(
            (f) => `
          <div class="field">
            <label>${f.label}</label>
            <input type="text" id="reportQr-${f.key}" placeholder="Scan or enter ${f.label}" />
          </div>`,
          ).join("")}
        </div>

        <div class="card card-pad" style="text-align:center;">
          <h3 style="margin:0 0 12px;font-size:13px;">FINAL RESULT</h3>
          <div style="font-size:34px;font-weight:800;color:${resultColor};">${resultText}</div>
          <div class="divider-line"></div>
          <div style="font-size:12px;color:var(--text-muted);text-align:left;">
            <div class="flex-between" style="padding:4px 0;"><span>Jig Firmware</span><span>${run.jig_firmware_version || "--"}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Jig Hardware</span><span>${run.jig_hardware_version || "--"}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Test Date/Time</span><span>${timeStr(run.start_time)}</span></div>
          </div>
        </div>
      </div>

      <div class="card" style="margin-bottom:16px;">
        <div class="card-header"><h3>PARAMETER RESULTS</h3></div>
        <table class="data-table">
          <thead><tr>
            <th>Parameter</th><th>Unit</th><th>Expected</th><th>Tolerance</th>
            <th>Measured</th><th>Deviation</th><th>Dev %</th><th>Status</th>
          </tr></thead>
          <tbody>
            ${run.parameters
              .map((p) => {
                const pillCls =
                  p.status === "PASS" ? "pill-pass" : p.status === "FAIL" ? "pill-fail" : "pill-pending";
                return `<tr>
                  <td>${p.name}</td><td>${p.unit}</td>
                  <td>${fmt(p.expected_value)}</td>
                  <td>±${fmt(p.tolerance)}</td>
                  <td>${fmt(p.measured_value)}</td>
                  <td>${p.deviation_value !== null ? (p.deviation_value >= 0 ? "+" : "") + fmt(p.deviation_value) : "--"}</td>
                  <td>${p.deviation_pct !== null ? (p.deviation_pct >= 0 ? "+" : "") + fmt(p.deviation_pct, 2) + "%" : "--"}</td>
                  <td><span class="pill ${pillCls}">${p.status}</span></td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table>
      </div>

      <div style="display:flex;gap:10px;">
        <button class="btn btn-ghost" id="reportCsvBtn">${icon("download", 14)} Save CSV</button>
        <button class="btn btn-primary" id="reportPdfBtn">${icon("download", 14)} Save PDF</button>
      </div>
    `;

    document.getElementById("reportBackBtn").addEventListener("click", () => App.showPage("dashboard"));
    document.getElementById("reportCsvBtn").addEventListener("click", () => save("csv"));
    document.getElementById("reportPdfBtn").addEventListener("click", () => save("pdf"));
  }

  function collectFieldValues() {
    const partNumber = document.getElementById("reportPartNumber").value.trim();
    const qrValues = {};
    QR_FIELDS.forEach((f) => {
      qrValues[f.label] = document.getElementById(`reportQr-${f.key}`).value.trim();
    });
    return { partNumber, qrValues };
  }

  async function save(fmtType) {
    const { partNumber, qrValues } = collectFieldValues();
    const runData = {
      ...run,
      charger_part_number: partNumber,
      qr_values: qrValues,
    };
    const res = await Backend.api().save_report(runData, fmtType);
    if (res.ok) App.toast(`Saved ${res.path}`, "success");
  }

  window.Pages = window.Pages || {};
  window.Pages.report = {
    onInit() {},
    onShow() {},
    onHide() {},
    // Called by dashboard.js right before navigating here after LOCK.
    // Report page never silently reuses a prior run's identification
    // fields (4.6) - each open() call re-renders from a fresh, blank form.
    open(lockedRun) {
      run = lockedRun;
      render();
    },
  };
})();
