(function () {
  const JIG_TILES = [
    {
      key: "ac_voltage_jig",
      label: "AC Voltage",
      unit: "V",
      accent: "var(--accent-aqua)",
    },
    {
      key: "ac_current_jig",
      label: "AC Current",
      unit: "A",
      accent: "var(--accent-aqua)",
    },
    {
      key: "ac_power_jig",
      label: "AC Power",
      unit: "W",
      accent: "var(--accent-aqua)",
      fmt: 1,
    },
    {
      key: "power_factor_jig",
      label: "Power Factor",
      unit: "",
      accent: "var(--accent-aqua)",
    },
    {
      key: "pfc_voltage",
      label: "PFC Voltage",
      unit: "V",
      accent: "var(--accent-aqua)",
    },
    {
      key: "sense_15v",
      label: "15V Sense",
      unit: "V",
      accent: "var(--accent-aqua)",
    },
    {
      key: "batt_voltage_jig",
      label: "Battery Voltage",
      unit: "V",
      accent: "var(--accent-aqua)",
    },
    {
      key: "batt_current_jig",
      label: "Battery Current",
      unit: "A",
      accent: "var(--accent-aqua)",
    },
    {
      key: "efficiency_jig",
      label: "Efficiency",
      unit: "%",
      accent: "var(--accent-aqua)",
      fmt: 2,
    },
  ];

  const DUT_TILES = [
    {
      key: "ac_voltage_dut",
      label: "AC Voltage",
      unit: "V",
      accent: "var(--primary)",
    },
    {
      key: "ac_current_dut",
      label: "AC Current",
      unit: "A",
      accent: "var(--primary)",
    },
    {
      key: "batt_voltage_dut",
      label: "Battery Voltage",
      unit: "V",
      accent: "var(--primary)",
    },
    {
      key: "batt_current_dut",
      label: "Battery Current",
      unit: "A",
      accent: "var(--primary)",
    },
  ];

  const TILE_SPECS = [...JIG_TILES, ...DUT_TILES];

  let recentFrames = [];
  let parameters = [];
  let phases = [];
  let started = false;
  let jigTestStarted = false;

  const AC_POWER_FACTOR = 0.99;
  const latestJig = {
    acVoltage: null,
    acCurrent: null,
    battVoltage: null,
    battCurrent: null,
  };

  function fmt(v, digits = 3) {
    return v === null || v === undefined ? "--" : Number(v).toFixed(digits);
  }

  function render() {
    const root = document.getElementById("page-dashboard");
    root.innerHTML = `
      <div id="dashRoot" style="height:calc(100vh - 64px - 64px);display:flex;flex-direction:column;overflow:hidden;">
      <div class="page-header" style="flex:0 0 auto;margin-bottom:10px;">
        <div><h1>Dashboard</h1><div class="page-sub">Live overview of JIG &amp; DUT signals and active test run</div></div>
      </div>

      <div class="card card-pad" style="flex:0 0 auto;margin-bottom:10px;padding:10px 14px;">
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;">
          <div class="field" style="min-width:160px;margin-bottom:0;">
            <label>COM Port</label>
            <select id="dashPortSel"></select>
          </div>
          <button class="btn btn-ghost btn-sm" id="dashRefreshBtn">${icon("refresh", 13)} Refresh</button>
          <div class="field" style="min-width:120px;margin-bottom:0;">
            <label>Baudrate</label>
            <input type="number" id="dashBaudInput" value="115200" min="9600" max="3000000" />
          </div>
          <button class="btn btn-primary" id="dashConnectBtn">${icon("plug", 14)} Connect</button>
          <button class="btn btn-danger" id="dashDisconnectBtn">${icon("unplug", 14)} Disconnect</button>
        </div>
      </div>

      <div class="grid-3" style="flex:0 0 auto;grid-template-columns: 220px 1fr 220px; margin-bottom:10px;">
        <div class="card card-pad" style="padding:10px 14px;">
          <h3 style="margin:0 0 8px;font-size:11.5px;letter-spacing:.4px;color:var(--text-secondary);">TEST CONTROL</h3>
          <div id="testStatusVal" style="text-align:center;padding:7px;border-radius:8px;font-weight:800;font-size:13px;letter-spacing:.4px;margin-bottom:8px;background:var(--status-critical-bg);color:#ff8a8a;">TEST STOPPED</div>
          ${infoRow("Test Duration", `<span id="testDurationVal" class="tabular">00:00:00</span>`)}
          ${infoRow("Start Time", `<span id="testStartVal" class="tabular">--:--:--</span>`)}
          ${infoRow("Stop Time", `<span id="testStopVal" class="tabular">--:--:--</span>`)}
        </div>

        <div class="card card-pad" style="padding:10px 14px;">
          <h3 style="margin:0 0 8px;font-size:11.5px;letter-spacing:.4px;color:var(--text-secondary);">LIVE MEASUREMENTS</h3>
          <div style="display:flex;gap:16px;align-items:flex-start;">
            <div style="flex:1;min-width:0;">
              <div style="font-size:10.5px;font-weight:700;letter-spacing:.4px;color:var(--accent-aqua);margin-bottom:6px;">JIG</div>
              <div class="stat-grid" id="tileGridJig" style="margin-bottom:0;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;"></div>
            </div>
            <div style="width:1px;align-self:stretch;background:var(--border);"></div>
            <div style="flex:1;min-width:0;">
              <div style="font-size:10.5px;font-weight:700;letter-spacing:.4px;color:var(--primary);margin-bottom:6px;">CHARGER</div>
              <div class="stat-grid" id="tileGridDut" style="margin-bottom:0;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;"></div>
            </div>
          </div>
        </div>

        <div class="card card-pad" style="padding:10px 14px;">
          <h3 style="margin:0 0 8px;font-size:11.5px;letter-spacing:.4px;color:var(--text-secondary);">TEST PROGRESS</h3>
          ${infoRow("Current Phase", `<span id="phaseVal" style="color:var(--primary-strong);font-weight:700;">Idle</span>`)}
          <div style="height:6px;border-radius:99px;background:var(--bg-input);margin:8px 0;overflow:hidden;">
            <div id="progressBar" style="height:100%;width:0%;background:linear-gradient(90deg,#3987e5,#5b6ff0);transition:width .3s;"></div>
          </div>
          <div style="text-align:right;font-size:11px;color:var(--text-muted);margin-bottom:8px;"><span id="progressCountVal">0 / 0</span></div>
          ${infoRow("Elapsed Time", `<span id="elapsedVal" class="tabular">00:00:00</span>`)}
          ${infoRow("Remaining Time", `<span id="remainingVal" class="tabular">--:--:--</span>`)}
          <div style="display:flex;gap:8px;margin-top:8px;text-align:center;">
            ${miniStat("Total", "totalStepsVal", "0")}
            ${miniStat("Done", "completedStepsVal", "0")}
            ${miniStat("Pending", "pendingStepsVal", "0")}
          </div>
        </div>
      </div>

      <div class="grid-3" style="flex:1 1 auto;min-height:0;grid-template-columns: 1fr 220px; margin-bottom:10px;">
        <div class="card" style="display:flex;flex-direction:column;min-height:0;">
          <div class="card-header" style="flex:0 0 auto;"><h3>PARAMETER COMPARISON</h3></div>
          <div class="table-scroll" style="flex:1 1 auto;min-height:0;">
            <table class="data-table">
              <thead><tr>
                <th>Parameter</th><th>Unit</th><th>Expected</th><th>Tolerance</th>
                <th>Measured</th><th>Deviation</th><th>Dev %</th><th>Status</th>
              </tr></thead>
              <tbody id="paramTableBody"></tbody>
            </table>
          </div>
        </div>

        <div class="card card-pad" style="text-align:center;padding:10px 14px;overflow:auto;">
          <h3 style="margin:0 0 8px;font-size:11.5px;letter-spacing:.4px;color:var(--text-secondary);">OVERALL RESULT</h3>
          <div id="overallBadge" style="width:56px;height:56px;border-radius:50%;margin:0 auto 8px;display:flex;align-items:center;justify-content:center;background:var(--bg-elevated);border:3px solid var(--border-strong);">${icon("clock", 24)}</div>
          <div id="overallLabel" style="font-size:16px;font-weight:800;color:var(--text-muted);margin-bottom:8px;">--</div>
          <div class="divider-line"></div>
          ${infoRow("Total Parameters", `<span id="totalParamsVal">0</span>`)}
          ${infoRow("Passed", `<span id="passedVal" style="color:#4ade80;">0</span>`)}
          ${infoRow("Failed", `<span id="failedVal" style="color:#ff8a8a;">0</span>`)}
          <div class="divider-line"></div>
          <div style="display:flex;gap:8px;">
            <button class="btn btn-ghost btn-sm" id="saveCsvBtn" style="flex:1;justify-content:center;">${icon("download", 13)} CSV</button>
            <button class="btn btn-ghost btn-sm" id="savePdfBtn" style="flex:1;justify-content:center;">${icon("download", 13)} PDF</button>
          </div>
        </div>
      </div>

      <div class="card" style="flex:0 0 auto;">
        <div class="card-header" style="padding:8px 14px;"><h3>RECENT CAN MESSAGES</h3>
          <button class="btn btn-ghost btn-sm" id="viewAllMsgBtn">VIEW ALL</button>
        </div>
        <table class="data-table">
          <thead><tr><th>Time</th><th>ID</th><th>Source</th><th>DLC</th><th>Data</th></tr></thead>
          <tbody id="msgTableBody"></tbody>
        </table>
      </div>
      </div>
    `;

    renderTiles();
    wireEvents();
  }

  function infoRow(label, valueHtml) {
    return `<div class="flex-between" style="padding:5px 0;font-size:12px;">
      <span style="color:var(--text-muted);">${label}</span>${valueHtml}
    </div>`;
  }

  function miniStat(label, id, value) {
    return `<div style="flex:1;background:var(--bg-elevated);border-radius:8px;padding:8px 4px;">
      <div style="font-size:9.5px;color:var(--text-muted);font-weight:700;text-transform:uppercase;">${label}</div>
      <div id="${id}" class="tabular" style="font-size:15px;font-weight:800;margin-top:2px;">${value}</div>
    </div>`;
  }

  function renderTileGroup(elId, tiles) {
    const grid = document.getElementById(elId);
    if (!grid) return;
    grid.innerHTML = tiles
      .map(
        (t) => `
      <div class="stat-tile" style="--tile-accent:${t.accent};padding:8px 10px;">
        <div class="stat-tile-label" style="font-size:9.5px;">${t.label}</div>
        <div class="stat-tile-value" id="tile-${t.key}" style="font-size:14px;margin-top:3px;">--<span class="unit">${t.unit}</span></div>
      </div>`,
      )
      .join("");
  }

  function renderTiles() {
    renderTileGroup("tileGridJig", JIG_TILES);
    renderTileGroup("tileGridDut", DUT_TILES);
  }

  function setTile(key, value, digits = 3) {
    const el = document.getElementById(`tile-${key}`);
    if (!el) return;
    const spec = TILE_SPECS.find((t) => t.key === key);
    el.innerHTML = `${fmt(value, digits)}<span class="unit">${spec.unit}</span>`;
  }

  function updateFromFrame(frame) {
    const s = frame.signals || {};
    if (frame.source === "JIG") {
      if ("mains_sense_dV" in s) setTile("ac_voltage_jig", s.mains_sense_dV);
      if ("ac_current_cA" in s) setTile("ac_current_jig", s.ac_current_cA);
      if ("ac_power_cW" in s) setTile("ac_power_jig", s.ac_power_cW, 1);
      if ("ac_power_factor_pct" in s)
        setTile("power_factor_jig", s.ac_power_factor_pct / 100.0);
      if ("pfc_voltage_v" in s) setTile("pfc_voltage", s.pfc_voltage_v);
      if ("pfc_15v_sense_v" in s) setTile("sense_15v", s.pfc_15v_sense_v);
      if ("batt_voltage_mv" in s)
        setTile("batt_voltage_jig", s.batt_voltage_mv);
      if ("batt_curr_sense_mv" in s)
        setTile("batt_current_jig", s.batt_curr_sense_mv * 10);

      if ("mains_sense_dV" in s) latestJig.acVoltage = s.mains_sense_dV;
      if ("ac_current_cA" in s) latestJig.acCurrent = s.ac_current_cA;
      if ("batt_voltage_mv" in s) latestJig.battVoltage = s.batt_voltage_mv;
      if ("batt_curr_sense_mv" in s)
        latestJig.battCurrent = s.batt_curr_sense_mv * 100;
      updateEfficiencyTile();

      if ("jig_status" in s) updateJigTestStatus(s.jig_status === 1);
    } else if (frame.source === "DUT") {
      if ("ACMains" in s) setTile("ac_voltage_dut", s.ACMains);
      if ("AC_Current" in s) setTile("ac_current_dut", s.AC_Current);
      if ("BatteryVoltage" in s) setTile("batt_voltage_dut", s.BatteryVoltage);
      if ("BatteryCurrent" in s) setTile("batt_current_dut", s.BatteryCurrent);
    }
  }

  function updateEfficiencyTile() {
    const { acVoltage, acCurrent, battVoltage, battCurrent } = latestJig;
    if (
      acVoltage == null ||
      acCurrent == null ||
      battVoltage == null ||
      battCurrent == null
    )
      return;

    const inputPower = acVoltage * acCurrent * AC_POWER_FACTOR;
    if (inputPower <= 0) return;

    const outputPower = battVoltage * battCurrent;
    setTile("efficiency_jig", (outputPower / inputPower) * 100, 2);
  }

  function updateJigTestStatus(isStarted) {
    if (isStarted === jigTestStarted) return;
    jigTestStarted = isStarted;

    const el = document.getElementById("testStatusVal");
    el.textContent = isStarted ? "TEST STARTED" : "TEST STOPPED";
    el.style.background = isStarted
      ? "var(--status-good-bg)"
      : "var(--status-critical-bg)";
    el.style.color = isStarted ? "#4ade80" : "#ff8a8a";

    if (isStarted) {
      Backend.api().start_test();
    } else {
      Backend.api().stop_test();
    }
  }

  function addFrameRow(frame) {
    recentFrames.unshift(frame);
    if (recentFrames.length > 200) recentFrames.pop();
    renderFrameRows();
  }

  function renderFrameRows() {
    const body = document.getElementById("msgTableBody");
    if (!body) return;
    body.innerHTML = recentFrames
      .slice(0, 5)
      .map(
        (f) => `<tr>
          <td class="tabular">${timeStr(f.timestamp)}</td>
          <td class="mono">${f.can_id_hex}</td>
          <td>${sourcePill(f.source)}</td>
          <td>${f.dlc}</td>
          <td class="mono">${f.payload_hex}</td>
        </tr>`,
      )
      .join("");
  }

  function sourcePill(source) {
    const cls =
      source === "JIG"
        ? "pill-jig"
        : source === "DUT"
          ? "pill-dut"
          : "pill-unknown";
    return `<span class="pill ${cls}">${source}</span>`;
  }

  function timeStr(ts) {
    return new Date(ts * 1000).toLocaleTimeString(undefined, { hour12: false });
  }

  function renderParams() {
    const body = document.getElementById("paramTableBody");
    if (!body) return;
    let pass = 0,
      fail = 0,
      pending = 0;
    body.innerHTML = parameters
      .map((p) => {
        if (p.status === "PASS") pass++;
        else if (p.status === "FAIL") fail++;
        else pending++;
        const pillCls =
          p.status === "PASS"
            ? "pill-pass"
            : p.status === "FAIL"
              ? "pill-fail"
              : "pill-pending";
        return `<tr>
          <td>${p.name}</td><td>${p.unit}</td>
          <td style="color:#4ade80;">${fmt(p.expected_value)}</td>
          <td>±${fmt(p.tolerance)}</td>
          <td style="color:var(--primary-strong);">${fmt(p.measured_value)}</td>
          <td style="color:#ff9a7a;">${p.deviation_value !== null ? (p.deviation_value >= 0 ? "+" : "") + fmt(p.deviation_value) : "--"}</td>
          <td style="color:#ff9a7a;">${p.deviation_pct !== null ? (p.deviation_pct >= 0 ? "+" : "") + fmt(p.deviation_pct, 2) + "%" : "--"}</td>
          <td><span class="pill ${pillCls}">${p.status}</span></td>
        </tr>`;
      })
      .join("");

    document.getElementById("totalParamsVal").textContent = parameters.length;
    document.getElementById("passedVal").textContent = pass;
    document.getElementById("failedVal").textContent = fail;

    const badge = document.getElementById("overallBadge");
    const label = document.getElementById("overallLabel");
    if (parameters.length === 0 || pending > 0) {
      badge.style.borderColor = "var(--border-strong)";
      badge.innerHTML = icon("clock", 30);
      label.textContent = "--";
      label.style.color = "var(--text-muted)";
    } else if (fail === 0) {
      badge.style.borderColor = "var(--status-good)";
      badge.innerHTML = icon("check_circle", 34);
      badge.style.color = "#4ade80";
      label.textContent = "PASS";
      label.style.color = "#4ade80";
    } else {
      badge.style.borderColor = "var(--status-critical)";
      badge.innerHTML = icon("stop", 30);
      badge.style.color = "#ff8a8a";
      label.textContent = "FAIL";
      label.style.color = "#ff8a8a";
    }
  }

  async function loadPorts() {
    const ports = await Backend.api().list_ports();
    const sel = document.getElementById("dashPortSel");
    if (!sel) return;
    sel.innerHTML = (ports.length ? ports : ["(none found)"]).map((p) => `<option>${p}</option>`).join("");
  }

  async function onConnect() {
    const port = document.getElementById("dashPortSel").value;
    const baud = parseInt(document.getElementById("dashBaudInput").value, 10) || 115200;
    const res = await Backend.api().connect(port, baud);
    if (res.ok) {
      App.setPcConnectionInfo(res.port, res.baudrate);
      App.toast("Connected", "success");
    }
  }

  async function onDisconnect() {
    await Backend.api().disconnect();
    App.setPcConnectionInfo("--", "--");
    App.toast("Disconnected", "success");
  }

  function wireEvents() {
    document.getElementById("dashRefreshBtn").addEventListener("click", loadPorts);
    document.getElementById("dashConnectBtn").addEventListener("click", onConnect);
    document.getElementById("dashDisconnectBtn").addEventListener("click", onDisconnect);
    document
      .getElementById("viewAllMsgBtn")
      .addEventListener("click", () => App.showPage("can_messages"));
    document
      .getElementById("saveCsvBtn")
      .addEventListener("click", () => saveReport("csv"));
    document
      .getElementById("savePdfBtn")
      .addEventListener("click", () => saveReport("pdf"));
  }

  async function saveReport(fmtType) {
    const run = await Backend.api().get_current_run();
    const runData = run || {
      run_id: "draft",
      start_time: Date.now() / 1000,
      end_time: null,
      phase: "",
      parameters,
    };
    runData.parameters = parameters;
    const res = await Backend.api().save_report(runData, fmtType);
    if (res.ok) App.toast(`Saved ${res.path}`, "success");
  }

  function onRunStarted(run) {
    started = true;
    document.getElementById("testStartVal").textContent = timeStr(
      run.start_time,
    );
    document.getElementById("testStopVal").textContent = "--:--:--";
  }

  function onRunStopped(run) {
    started = false;
    if (run.end_time) {
      document.getElementById("testStopVal").textContent = timeStr(
        run.end_time,
      );
      const elapsed = run.end_time - run.start_time;
      document.getElementById("testDurationVal").textContent =
        fmtDuration(elapsed);
    }
  }

  function fmtDuration(seconds) {
    const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
    const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
    const s = String(Math.floor(seconds % 60)).padStart(2, "0");
    return `${h}:${m}:${s}`;
  }

  function onPhase(data) {
    document.getElementById("phaseVal").textContent = data.phase;
    const idx = phases.indexOf(data.phase);
    const total = phases.length || 1;
    const done = idx >= 0 ? idx : 0;
    document.getElementById("progressBar").style.width =
      `${(done / total) * 100}%`;
    document.getElementById("progressCountVal").textContent =
      `${done} / ${phases.length}`;
    document.getElementById("completedStepsVal").textContent = done;
    document.getElementById("pendingStepsVal").textContent = Math.max(
      phases.length - done,
      0,
    );
  }

  let tickTimer = null;
  function startTick() {
    if (tickTimer) return;
    tickTimer = setInterval(async () => {
      const run = await Backend.api().get_current_run();
      if (run) {
        document.getElementById("testDurationVal").textContent = fmtDuration(
          run.elapsed,
        );
        document.getElementById("elapsedVal").textContent = fmtDuration(
          run.elapsed,
        );
      }
    }, 1000);
  }

  function stopTick() {
    if (tickTimer) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
  }

  let unsubscribers = [];

  window.Pages = window.Pages || {};
  window.Pages.dashboard = {
    async onInit() {
      render();
      phases = await Backend.api().get_phases();
      document.getElementById("totalStepsVal").textContent = phases.length;
      document.getElementById("pendingStepsVal").textContent = phases.length;
      document.getElementById("progressCountVal").textContent =
        `0 / ${phases.length}`;

      parameters = await Backend.api().get_parameters();
      renderParams();

      await loadPorts();
      const info = await Backend.api().get_connection_info();
      App.setPcConnectionInfo(info.port, info.baudrate);
    },
    async onShow() {
      const frames = await Backend.api().get_recent_frames(200);
      recentFrames = frames.slice().reverse();
      renderFrameRows();

      unsubscribers = [
        Backend.on("frame", (f) => {
          addFrameRow(f);
          updateFromFrame(f);
        }),
        Backend.on("parameters", (p) => {
          if (!jigTestStarted) return;
          parameters = p;
          renderParams();
        }),
        Backend.on("run_started", onRunStarted),
        Backend.on("run_stopped", onRunStopped),
        Backend.on("phase", onPhase),
      ];

      startTick();
    },
    onHide() {
      unsubscribers.forEach((fn) => fn());
      unsubscribers = [];
      stopTick();
    },
  };
})();
