(function () {
  const CAPACITY = 5000;
  const DISPLAY_CAP = 500;
  let allFrames = [];
  let knownMessages = new Set();
  let sourceFilter = "All";
  let messageFilter = "All";

  function render() {
    document.getElementById("page-can_messages").innerHTML = `
      <div class="page-header">
        <div><h1>CAN Messages</h1><div class="page-sub">Full-history CAN traffic with source and message filters</div></div>
      </div>
      <div class="flex-gap" style="margin-bottom:14px;">
        <span style="font-size:12px;color:var(--text-muted);font-weight:700;">Source</span>
        <select id="cmSourceSel" style="background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12px;">
          <option>All</option><option>JIG</option><option>DUT</option><option>UNKNOWN</option>
        </select>
        <span style="font-size:12px;color:var(--text-muted);font-weight:700;margin-left:10px;">Message</span>
        <select id="cmMessageSel" style="background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12px;">
          <option>All</option>
        </select>
        <button class="btn btn-ghost btn-sm" id="cmClearBtn" style="margin-left:auto;">${icon("trash", 13)} Clear</button>
      </div>
      <div class="card">
        <div class="table-scroll" style="max-height:calc(100vh - 230px);">
          <table class="data-table">
            <thead><tr><th>Time</th><th>ID (hex)</th><th>Source</th><th>Message</th><th>DLC</th><th>Data</th></tr></thead>
            <tbody id="cmBody"></tbody>
          </table>
        </div>
      </div>
    `;

    document.getElementById("cmSourceSel").addEventListener("change", (e) => {
      sourceFilter = e.target.value;
      refresh();
    });
    document.getElementById("cmMessageSel").addEventListener("change", (e) => {
      messageFilter = e.target.value;
      refresh();
    });
    document.getElementById("cmClearBtn").addEventListener("click", () => {
      allFrames = [];
      refresh();
    });
  }

  function timeStr(ts) {
    return new Date(ts * 1000).toLocaleTimeString(undefined, { hour12: false });
  }

  function passesFilter(f) {
    if (sourceFilter !== "All" && f.source !== sourceFilter) return false;
    if (messageFilter !== "All" && f.message_name !== messageFilter) return false;
    return true;
  }

  function rowHtml(f) {
    const cls = f.source === "JIG" ? "pill-jig" : f.source === "DUT" ? "pill-dut" : "pill-unknown";
    return `<tr>
      <td class="tabular">${timeStr(f.timestamp)}</td>
      <td class="mono">${f.can_id_hex}</td>
      <td><span class="pill ${cls}">${f.source}</span></td>
      <td>${f.message_name}</td>
      <td>${f.dlc}</td>
      <td class="mono">${f.payload_hex}</td>
    </tr>`;
  }

  function refresh() {
    const body = document.getElementById("cmBody");
    if (!body) return;
    const rows = allFrames
      .slice(-DISPLAY_CAP)
      .slice()
      .reverse()
      .filter(passesFilter);
    body.innerHTML = rows.map(rowHtml).join("");
  }

  function onFrame(frame) {
    allFrames.push(frame);
    if (allFrames.length > CAPACITY) allFrames.shift();

    if (!knownMessages.has(frame.message_name)) {
      knownMessages.add(frame.message_name);
      const sel = document.getElementById("cmMessageSel");
      if (sel) {
        const opt = document.createElement("option");
        opt.textContent = frame.message_name;
        sel.appendChild(opt);
      }
    }

    if (passesFilter(frame)) {
      const body = document.getElementById("cmBody");
      if (body) {
        body.insertAdjacentHTML("afterbegin", rowHtml(frame));
        while (body.children.length > DISPLAY_CAP) body.removeChild(body.lastChild);
      }
    }
  }

  let unsubscribe = null;

  window.Pages = window.Pages || {};
  window.Pages.can_messages = {
    onInit() {
      render();
    },
    onShow() {
      unsubscribe = Backend.on("frame", onFrame);
    },
    onHide() {
      if (unsubscribe) {
        unsubscribe();
        unsubscribe = null;
      }
    },
  };
})();
