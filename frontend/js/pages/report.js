(function () {
  // CR-05/4.6: identification fields on the report page. Array-driven so
  // more QR fields can be appended later without touching render logic.
  const QR_FIELDS = [
    { key: "qr_code_1", label: "Control Board QR", prefix: "ADTAA" },
    { key: "qr_code_2", label: "Energy Meter QR", prefix: "ADTAB" },
    { key: "qr_code_3", label: "Main Board QR", prefix: "ADTAC" },
  ];

  let run = null;
  let lots = [];
  let generatedSerial = "";
  let submittedReport = null; // server's stored report, once submitted
  let selectedLotId = ""; // preserved across re-renders (e.g. after submit)
  let qrValues = { qr_code_1: "", qr_code_2: "", qr_code_3: "" }; // preserved across re-renders

  function lotLabel(lot) {
    const monthYear = `${lot.month_code}${lot.year_code}`;
    return `Lot ${lot.lot_code_display} — ${monthYear} — ${lot.prefix}`;
  }

  // Model No. comes from the lot's voltage_amp_code ("5825"/"7325" - first
  // 2 digits = voltage, last 2 = amps, per VOLTAGE_AMP_CHOICES in the
  // server's charger_code_tables.py), formatted for display as "CCP58V25A"
  // ("CCP" prefix on every generated report, regardless of source code).
  function formatModelNo(code) {
    if (!code || code.length !== 4) return code || "--";
    return `CCP${code.slice(0, 2)}V${code.slice(2)}A`;
  }

  function modelNo() {
    if (submittedReport) return formatModelNo(submittedReport.voltage_amp_code);
    const lot = lots.find((l) => String(l.id) === String(selectedLotId));
    return formatModelNo(lot && lot.voltage_amp_code);
  }

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
        <div><h1>Test Report</h1><div class="page-sub">${timeStr(run.start_time)}</div></div>
        <button class="btn btn-ghost btn-sm" id="reportBackBtn">${icon("dashboard", 13)} Back to Dashboard</button>
      </div>

      <div class="grid-2" style="margin-bottom:16px;">
        <div class="card card-pad">
          <h3 style="margin:0 0 12px;font-size:13px;">IDENTIFICATION</h3>
          <div class="field">
            <label>Lot</label>
            <div style="display:flex;gap:8px;">
              <select id="reportLotSel" ${generatedSerial ? "disabled" : ""}><option value="">Loading lots...</option></select>
              <button class="btn btn-ghost btn-sm" id="reportFetchLotsBtn" type="button" title="Fetch lots" ${generatedSerial ? "disabled" : ""}>${icon("refresh", 13)}</button>
            </div>
          </div>
          ${QR_FIELDS.map((f, i) => {
            // Sequential unlock: a field is enabled once all fields before it
            // are filled (or it's the first one). Keeps scans in order —
            // Control Board -> Energy Meter -> Main Board.
            const prevFilled = i === 0 || QR_FIELDS.slice(0, i).every((pf) => qrValues[pf.key]);
            const locked = generatedSerial || !prevFilled;
            return `<div class="field">
              <label>${f.label}</label>
              <input type="text" id="report_${f.key}" class="report-qr-input" data-key="${f.key}" value="${qrValues[f.key] || ""}" placeholder="${prevFilled ? `Scan or enter ${f.label}` : "Scan previous QR first"}" ${locked ? "readonly" : ""} />
            </div>`;
          }).join("")}
          <div class="field">
            <label>Serial Number</label>
            <div style="display:flex;gap:8px;">
              <input type="text" id="reportSerialNumber" placeholder="Not generated yet" readonly />
              <button class="btn btn-primary btn-sm" id="reportGenSerialBtn" style="white-space:nowrap;display:none;">${icon("check_circle", 13)} Generate Serial Number</button>
            </div>
          </div>
        </div>

        <div class="card card-pad" style="text-align:center;">
          <h3 style="margin:0 0 12px;font-size:13px;">FINAL RESULT</h3>
          <div style="font-size:34px;font-weight:800;color:${resultColor};">${resultText}</div>
          <div class="divider-line"></div>
          <div style="font-size:12px;color:var(--text-muted);text-align:left;">
            <div class="flex-between" style="padding:4px 0;"><span>Report No.</span><span>${(submittedReport && submittedReport.report_id) || "Not generated yet"}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Model No.</span><span id="reportModelNoVal">${modelNo()}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Charger Firmware</span><span>${run.dut_firmware_version || "--"}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Charger Hardware</span><span>${run.dut_hardware_version || "--"}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Jig Firmware</span><span>${run.jig_firmware_version || "--"}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Jig Hardware</span><span>${run.jig_hardware_version || "--"}</span></div>
            <div class="flex-between" style="padding:4px 0;"><span>Ambient Temperature</span><span>${run.ambient_temperature && run.ambient_temperature !== "--" ? `${run.ambient_temperature} °C` : "--"}</span></div>
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
    document.getElementById("reportGenSerialBtn").addEventListener("click", onGenerateSerial);
    document.querySelectorAll(".report-qr-input").forEach((el) => {
      // "input" only keeps the Generate button's visibility live - it never
      // re-renders, so it's safe during a fast scanner's keystroke burst.
      // Unlocking the next field happens on blur/Enter (onQrCommit), once
      // the scan is actually done, so a mid-scan re-render can't steal focus
      // and swallow characters.
      el.addEventListener("input", updateGenerateButtonVisibility);
      el.addEventListener("blur", onQrCommit);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") el.blur();
      });
    });
    document.getElementById("reportLotSel").addEventListener("change", (e) => {
      selectedLotId = e.target.value;
      const modelEl = document.getElementById("reportModelNoVal");
      if (modelEl) modelEl.textContent = modelNo();
      updateGenerateButtonVisibility();
      // Remember this lot on this machine so the next report defaults to it too.
      const lot = lots.find((l) => String(l.id) === String(selectedLotId));
      Backend.api().set_last_lot(selectedLotId, lot ? lotLabel(lot) : "");
    });
    document.getElementById("reportFetchLotsBtn").addEventListener("click", loadLots);

    renderSerialField();
    loadLots();
  }

  // Fires once a QR field is left (blur, or Enter which triggers a blur) -
  // i.e. once the scan/typing into it is actually done. Re-renders (to
  // unlock the next field, or re-lock later ones if this value was cleared)
  // only when this field's filled/empty state actually changed.
  function onQrCommit(e) {
    const key = e.target.dataset.key;
    const field = QR_FIELDS.find((f) => f.key === key);
    const wasFilled = !!qrValues[key];
    let value = e.target.value.trim();
    // Each QR must belong to its own board - reject (and clear) a value that
    // doesn't carry the right prefix, e.g. a Control Board QR (ADTAA...)
    // scanned into the Energy Meter slot (which requires ADTAB...), so a
    // mismatched board can never make it into the report.
    if (value && field && field.prefix && !value.startsWith(field.prefix)) {
      App.toast(`${field.label} must start with "${field.prefix}"`, "error");
      value = "";
      e.target.value = "";
    }
    qrValues[key] = value;
    const isFilled = !!qrValues[key];
    if (wasFilled !== isFilled) {
      const idx = QR_FIELDS.findIndex((f) => f.key === key);
      render();
      // Move focus to the next field once it unlocks, so an operator scanning
      // straight through doesn't have to click into the next box by hand.
      // Deferred to the next frame: render() just replaced the whole
      // #page-report subtree via innerHTML (destroying the input that's
      // still mid-blur), and focusing the freshly-inserted element in the
      // same tick races that reflow - the webview can drop the focus call
      // and leave nothing focused, which is why the cursor never lands.
      const nextField = isFilled && QR_FIELDS[idx + 1];
      if (nextField) {
        requestAnimationFrame(() => {
          const nextEl = document.getElementById(`report_${nextField.key}`);
          if (nextEl) nextEl.focus();
        });
      }
    } else {
      updateGenerateButtonVisibility();
    }
  }

  function collectQrValues() {
    QR_FIELDS.forEach((f) => {
      const el = document.getElementById(`report_${f.key}`);
      let value = el ? el.value.trim() : "";
      if (value && f.prefix && !value.startsWith(f.prefix)) value = "";
      qrValues[f.key] = value;
    });
    return qrValues;
  }

  // Generate Serial Number only becomes visible once a lot is selected and
  // all 3 QR fields are filled in - it stays hidden until then so a report
  // can never be submitted with missing traceability data.
  function updateGenerateButtonVisibility() {
    const btn = document.getElementById("reportGenSerialBtn");
    if (!btn || generatedSerial) return;
    const lotId = document.getElementById("reportLotSel").value;
    const qrValues = collectQrValues();
    const allQrFilled = QR_FIELDS.every((f) => qrValues[f.key]);
    btn.style.display = lotId && allQrFilled ? "" : "none";
  }

  function renderSerialField() {
    const input = document.getElementById("reportSerialNumber");
    if (input) input.value = generatedSerial;
  }

  async function loadLots() {
    const sel = document.getElementById("reportLotSel");
    if (!sel) return;
    sel.innerHTML = `<option value="">Loading lots...</option>`;
    const res = await Backend.api().list_lots();
    if (!res.ok) {
      sel.innerHTML = `<option value="">Failed to load lots</option>`;
      App.toast(res.error || "Failed to load lots", "error");
      return;
    }
    lots = res.lots || [];
    if (!lots.length) {
      sel.innerHTML = `<option value="">No lots yet — create one on the Lot page</option>`;
      return;
    }
    sel.innerHTML = `<option value="">Select a lot...</option>` +
      lots.map((l) => `<option value="${l.id}">${lotLabel(l)}</option>`).join("");
    if (selectedLotId) sel.value = selectedLotId;
    updateGenerateButtonVisibility();
  }

  // Report submission (CR): once all 3 QR codes + a lot are filled in,
  // clicking this submits the locked run to the server, which atomically
  // generates the serial number AND stores the report against it. The
  // server's returned report (serial included) is auto-saved locally by the
  // backend, so this is the single point where a serial gets minted.
  async function onGenerateSerial() {
    const lotId = selectedLotId;
    if (!lotId) {
      App.toast("Select a lot first", "error");
      return;
    }
    const values = collectQrValues();
    if (QR_FIELDS.some((f) => !values[f.key])) {
      App.toast("Enter all 3 QR values first", "error");
      return;
    }

    const btn = document.getElementById("reportGenSerialBtn");
    btn.disabled = true;
    try {
      const res = await Backend.api().submit_charger_report(lotId, values, run);
      if (res.ok) {
        submittedReport = res.report;
        generatedSerial = res.report.serial_number;
        render();
        const savedMsg = res.saved_path ? ` — saved locally` : "";
        App.toast(`Serial number ${generatedSerial} generated${savedMsg}`, "success");
      } else {
        App.toast(res.error || "Failed to submit report", "error");
      }
    } finally {
      btn.disabled = false;
    }
  }

  async function save(fmtType) {
    const runData = {
      ...run,
      charger_part_number: "",
      model_no: modelNo(),
      ambient_temperature: run.ambient_temperature,
      qr_values: collectQrValues(),
      serial_number: generatedSerial,
      report_id: (submittedReport && submittedReport.report_id) || "",
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
    // The Lot is the one exception: it's remembered on this machine (set_last_lot,
    // persisted to disk) and pre-selected here, since operators typically run a
    // long batch of chargers from the same lot and re-picking it every single
    // report is pure friction with no traceability benefit - the QR fields
    // (which actually identify the individual unit) still always start blank.
    async open(lockedRun) {
      run = lockedRun;
      generatedSerial = "";
      submittedReport = null;
      qrValues = { qr_code_1: "", qr_code_2: "", qr_code_3: "" };
      const last = await Backend.api().get_last_lot();
      selectedLotId = (last.ok && last.lot_id) ? String(last.lot_id) : "";
      render();
    },
  };
})();
