// Global "no data from JIG" banner. Independent of any single page (like
// update_banner.js) since the JIG can go silent while the user is anywhere
// in the app. Listens for the "data_status" event bridge.py's Api._push()
// sends when SerialWorker sees no bytes for STALL_SECONDS on an open port,
// and again (stalled: false) when data resumes or the link is closed.

(function () {
  let bar = null;
  let timer = null;

  function hide() {
    if (timer) clearInterval(timer);
    timer = null;
    if (bar) bar.remove();
    bar = null;
  }

  function show(initialSeconds) {
    hide();
    const shownAt = Date.now() - initialSeconds * 1000;

    bar = document.createElement("div");
    bar.id = "data-watch-banner";
    bar.setAttribute("role", "alert");
    bar.style.cssText = [
      "position:fixed", "top:76px", "left:50%", "transform:translateX(-50%)", "z-index:9998",
      "max-width:min(760px, calc(100vw - 32px))", "display:flex", "align-items:flex-start", "gap:12px",
      "padding:12px 16px", "background:var(--bg-elevated)", "color:var(--text-primary)",
      "border:1px solid var(--status-warning)", "border-left:4px solid var(--status-warning)",
      "border-radius:var(--radius-sm)", "box-shadow:var(--shadow-pop)", "font-size:13px", "line-height:1.45",
    ].join(";");

    const text = document.createElement("div");
    const title = document.createElement("div");
    title.style.cssText = "font-weight:700;color:var(--status-warning);";
    const hint = document.createElement("div");
    hint.style.cssText = "color:var(--text-secondary);";
    hint.textContent =
      "Check that the charger is connected and powered on. " +
      "If data doesn't come back, unplug the JIG's USB cable, plug it back in, and click Connect.";
    text.append(title, hint);

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Dismiss";
    closeBtn.style.cssText =
      "flex:0 0 auto;background:transparent;color:var(--text-secondary);border:1px solid var(--border-strong);" +
      "border-radius:4px;padding:4px 10px;cursor:pointer;";
    closeBtn.onclick = hide;

    const tick = () => {
      const secs = Math.round((Date.now() - shownAt) / 1000);
      title.textContent = `No data from the JIG for ${secs} s`;
    };
    tick();
    timer = setInterval(tick, 1000);

    bar.append(text, closeBtn);
    document.body.appendChild(bar);
  }

  Backend.on("data_status", (data) => {
    if (data.stalled) show(data.seconds || 0);
    else hide();
  });
  Backend.on("connection", (data) => {
    if (!data.connected) hide();
  });
})();
