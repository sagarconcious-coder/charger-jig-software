const PAGES = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard" },
  { id: "can_messages", label: "CAN Messages", icon: "can_messages" },
  { id: "configuration", label: "Configuration", icon: "configuration" },
];

const App = {
  currentPage: "dashboard",

  renderShell() {
    document.getElementById("topbar").innerHTML = this.topbarHtml();
    document.getElementById("sidebar").innerHTML = this.sidebarHtml();

    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => this.showPage(btn.dataset.page));
    });
  },

  topbarHtml() {
    return `
      <div class="brand">
        <div class="brand-mark">⚡</div>
        <div class="brand-text">
          <h1>CHARGER TESTING JIG</h1>
          <p>CAN Monitor &amp; Test System</p>
        </div>
      </div>
      <div style="flex:1"></div>
      <div class="flex-gap" style="margin-right:22px;">
        <span style="font-size:11px;color:var(--text-muted);font-weight:700;">System Status</span>
        <span id="systemStatusBadge">${this.badgeHtml(false, "CONNECTED", "DISCONNECTED")}</span>
      </div>
      <div class="flex-gap" style="margin-right:22px;">
        <span style="font-size:11px;color:var(--text-muted);font-weight:700;">CAN Status</span>
        <span id="canStatusBadge">${this.badgeHtml(false, "ACTIVE", "IDLE")}</span>
      </div>
      <div class="flex-gap" style="margin-right:22px;">
        <span style="font-size:11px;color:var(--text-muted);font-weight:700;">DBC Loaded</span>
        <span id="dbcLoadedLabel" style="font-size:11.5px;color:var(--text-secondary);font-weight:600;">--</span>
      </div>
      <div style="margin-left:16px;text-align:right;line-height:1.25;">
        <div id="dateLabel" style="font-size:11px;color:var(--text-muted);"></div>
        <div id="timeLabel" style="font-size:12.5px;font-weight:700;" class="tabular"></div>
      </div>
    `;
  },

  badgeHtml(active, onText, offText) {
    return active
      ? `<span class="badge badge-good"><span class="dot"></span>${onText}</span>`
      : `<span class="badge badge-off"><span class="dot off"></span>${offText}</span>`;
  },

  sidebarHtml() {
    const navItems = PAGES.map(
      (p) => `<button class="nav-btn" data-page="${p.id}">${icon(p.icon, 17)}<span>${p.label.toUpperCase()}</span></button>`
    ).join("");
    return `
      ${navItems}
      <div class="nav-spacer"></div>
      <div class="pc-panel">
        <div class="pc-panel-title"><span class="dot" id="pcDot"></span>PC CONNECTION</div>
        <div class="pc-row"><span>CAN Interface</span><span id="pcInterface">--</span></div>
        <div class="pc-row"><span>Baudrate</span><span id="pcBaudrate">--</span></div>
        <div class="pc-row"><span>FW Version</span><span>1.0.0</span></div>
      </div>
    `;
  },

  showPage(id) {
    if (this.currentPage && this.currentPage !== id) {
      const prevMod = window.Pages && window.Pages[this.currentPage];
      if (prevMod && prevMod.onHide) prevMod.onHide();
    }

    this.currentPage = id;
    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.page === id);
    });
    document.querySelectorAll(".page").forEach((el) => {
      el.classList.toggle("active", el.id === `page-${id}`);
    });
    const mod = window.Pages && window.Pages[id];
    if (mod && mod.onShow) mod.onShow();
  },

  startClock() {
    const tick = () => {
      const now = new Date();
      const dateLabel = document.getElementById("dateLabel");
      const timeLabel = document.getElementById("timeLabel");
      if (dateLabel) {
        dateLabel.textContent = now.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
      }
      if (timeLabel) {
        timeLabel.textContent = now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      }
    };
    tick();
    setInterval(tick, 1000);
  },

  onConnectionChanged(data) {
    const sys = document.getElementById("systemStatusBadge");
    const can = document.getElementById("canStatusBadge");
    const dot = document.getElementById("pcDot");
    if (sys) sys.innerHTML = this.badgeHtml(data.connected, "CONNECTED", "DISCONNECTED");
    if (can) can.innerHTML = this.badgeHtml(data.connected, "ACTIVE", "IDLE");
    if (dot) dot.classList.toggle("off", !data.connected);
  },

  setDbcLoadedLabel(text) {
    const el = document.getElementById("dbcLoadedLabel");
    if (el) el.textContent = text || "--";
  },

  setPcConnectionInfo(port, baud) {
    const i = document.getElementById("pcInterface");
    const b = document.getElementById("pcBaudrate");
    if (i) i.textContent = port || "--";
    if (b) b.textContent = baud || "--";
  },

  toast(message, type = "success") {
    let container = document.querySelector(".toast-container");
    if (!container) {
      container = document.createElement("div");
      container.className = "toast-container";
      document.body.appendChild(container);
    }
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  },
};

window.addEventListener("DOMContentLoaded", async () => {
  await Backend.whenReady();

  App.renderShell();
  App.startClock();
  Backend.on("connection", (d) => App.onConnectionChanged(d));

  const status = await Backend.api().get_dbc_status();
  const names = [status.jig_path, status.dut_path].filter(Boolean).join(", ");
  App.setDbcLoadedLabel(names);

  window.Pages && Object.values(window.Pages).forEach((p) => p.onInit && p.onInit());

  App.showPage(App.currentPage);
});
