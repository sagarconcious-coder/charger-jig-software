(function () {
  // Lot creation page: operator picks the 6 traceability codes (everything
  // in the QR serial number except the lot code itself and the running
  // serial sequence, both of which the server auto-increments) and submits
  // to create a new lot. The Test Report page then generates serial numbers
  // against whichever lot is selected there.

  let options = null; // { voltage_amp, variant, connector, ms_id, month, year, defaults }
  let lots = [];

  function render() {
    const root = document.getElementById("page-lot");
    root.innerHTML = `
      <div class="page-header">
        <div><h1>Lot</h1><div class="page-sub">Create a traceability lot for charger serial numbers</div></div>
      </div>

      <div class="grid-2" style="margin-bottom:16px;">
        <div class="card card-pad">
          <h3 style="margin:0 0 12px;font-size:13px;">NEW LOT</h3>
          <div class="field">
            <label>Voltage &amp; Amp</label>
            <select id="lotVoltageAmp"></select>
          </div>
          <div class="field">
            <label>Variant</label>
            <select id="lotVariant"></select>
          </div>
          <div class="field">
            <label>Output Connector</label>
            <select id="lotConnector"></select>
          </div>
          <div class="field">
            <label>MS Identification</label>
            <select id="lotMsId"></select>
          </div>
          <div class="field">
            <label>Month</label>
            <select id="lotMonth"></select>
          </div>
          <div class="field">
            <label>Year</label>
            <select id="lotYear"></select>
          </div>
          <button class="btn btn-primary" id="lotCreateBtn" style="width:100%;justify-content:center;margin-top:6px;">${icon("check_circle", 14)} Create Lot</button>
        </div>

        <div class="card card-pad" style="text-align:center;">
          <h3 style="margin:0 0 12px;font-size:13px;">PREVIEW PREFIX</h3>
          <div id="lotPreviewPrefix" style="font-size:24px;font-weight:800;letter-spacing:1px;color:var(--primary-strong);">--</div>
          <div class="divider-line"></div>
          <div style="font-size:12px;color:var(--text-muted);">
            Full serial = Prefix + Lot Code (2 digits) + Running Serial No. (5 digits)<br/>
            e.g. <span class="tabular">CC5825AAGHB0100001</span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3>EXISTING LOTS</h3></div>
        <table class="data-table">
          <thead><tr>
            <th>Lot Code</th><th>Month</th><th>Year</th><th>Prefix</th><th>Next Sr. No.</th><th>Created</th>
          </tr></thead>
          <tbody id="lotTableBody"></tbody>
        </table>
      </div>
    `;

    wireEvents();
  }

  function fillSelect(id, choices, selectedCode) {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = choices.map((c) => `<option value="${c.code}">${c.label}</option>`).join("");
    if (selectedCode) sel.value = selectedCode;
  }

  function applyOptions() {
    if (!options) return;
    fillSelect("lotVoltageAmp", options.voltage_amp, options.defaults.voltage_amp_code);
    fillSelect("lotVariant", options.variant, options.defaults.variant_code);
    fillSelect("lotConnector", options.connector, options.defaults.connector_code);
    fillSelect("lotMsId", options.ms_id, options.defaults.ms_id_code);
    fillSelect("lotMonth", options.month, options.defaults.month_code);
    fillSelect("lotYear", options.year, options.defaults.year_code);
    updatePreview();
  }

  function updatePreview() {
    const el = document.getElementById("lotPreviewPrefix");
    if (!el) return;
    const va = document.getElementById("lotVoltageAmp").value;
    const variant = document.getElementById("lotVariant").value;
    const connector = document.getElementById("lotConnector").value;
    const msId = document.getElementById("lotMsId").value;
    const month = document.getElementById("lotMonth").value;
    const year = document.getElementById("lotYear").value;
    el.textContent = `CC${va}${variant}${connector}${msId}${month}${year}`;
  }

  async function loadOptions() {
    const res = await Backend.api().get_lot_options();
    if (!res.ok) {
      App.toast(res.error || "Failed to load lot options", "error");
      return;
    }
    options = res;
    applyOptions();
  }

  function renderLotsTable() {
    const body = document.getElementById("lotTableBody");
    if (!body) return;
    if (!lots.length) {
      body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">No lots created yet</td></tr>`;
      return;
    }
    body.innerHTML = lots
      .map(
        (l) => `<tr>
          <td>${l.lot_code_display}</td>
          <td>${l.month_code}</td>
          <td>${l.year_code}</td>
          <td class="tabular">${l.prefix}</td>
          <td>${String(l.next_seq).padStart(5, "0")}</td>
          <td>${l.created_at ? new Date(l.created_at).toLocaleString(undefined, { hour12: false }) : "--"}</td>
        </tr>`,
      )
      .join("");
  }

  async function loadLots() {
    const res = await Backend.api().list_lots();
    if (!res.ok) {
      App.toast(res.error || "Failed to load lots", "error");
      return;
    }
    lots = res.lots || [];
    renderLotsTable();
  }

  async function onCreateLot() {
    const codes = {
      voltage_amp_code: document.getElementById("lotVoltageAmp").value,
      variant_code: document.getElementById("lotVariant").value,
      connector_code: document.getElementById("lotConnector").value,
      ms_id_code: document.getElementById("lotMsId").value,
      month_code: document.getElementById("lotMonth").value,
      year_code: document.getElementById("lotYear").value,
    };
    const btn = document.getElementById("lotCreateBtn");
    btn.disabled = true;
    try {
      const res = await Backend.api().create_lot(codes);
      if (res.ok) {
        App.toast(`Lot ${res.lot.lot_code_display} created (${res.lot.prefix})`, "success");
        await loadLots();
      } else {
        App.toast(res.error || "Failed to create lot", "error");
      }
    } finally {
      btn.disabled = false;
    }
  }

  function wireEvents() {
    document.getElementById("lotCreateBtn").addEventListener("click", onCreateLot);
    ["lotVoltageAmp", "lotVariant", "lotConnector", "lotMsId", "lotMonth", "lotYear"].forEach((id) => {
      document.getElementById(id).addEventListener("change", updatePreview);
    });
  }

  window.Pages = window.Pages || {};
  window.Pages.lot = {
    onInit() {},
    async onShow() {
      render();
      await loadOptions();
      await loadLots();
    },
    onHide() {},
  };
})();
