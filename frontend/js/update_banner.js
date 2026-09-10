// Global "update ready" banner. Independent of any single page (like api.js)
// since an update can be found while the user is anywhere in the app.
// Listens for the "update_ready" event bridge.py's Api._push() sends once a
// newer .exe has already been downloaded in the background.

(function () {
  function buildBanner(version) {
    const bar = document.createElement("div");
    bar.id = "update-banner";
    bar.style.cssText = [
      "position:fixed", "left:0", "right:0", "bottom:0", "z-index:9999",
      "display:flex", "align-items:center", "justify-content:center", "gap:12px",
      "padding:10px 16px", "background:#0F766E", "color:#fff",
      "font:14px system-ui, sans-serif", "box-shadow:0 -2px 8px rgba(0,0,0,.25)",
    ].join(";");

    const label = document.createElement("span");
    label.textContent = `Update ${version} is ready to install.`;

    const restartBtn = document.createElement("button");
    restartBtn.textContent = "Restart now";
    restartBtn.style.cssText =
      "background:#fff;color:#0F766E;border:none;border-radius:4px;padding:6px 12px;cursor:pointer;font-weight:600;";
    restartBtn.onclick = async () => {
      restartBtn.disabled = true;
      restartBtn.textContent = "Restarting...";
      try {
        await window.pywebview.api.apply_update();
        // apply_update() ends this process via sys.exit(0) on the Python
        // side once the helper script is launched - the window will close
        // on its own; nothing more to do here.
      } catch (err) {
        console.error("Failed to apply update", err);
        restartBtn.disabled = false;
        restartBtn.textContent = "Restart now";
      }
    };

    const laterBtn = document.createElement("button");
    laterBtn.textContent = "Later";
    laterBtn.style.cssText =
      "background:transparent;color:#fff;border:1px solid rgba(255,255,255,.5);border-radius:4px;padding:6px 12px;cursor:pointer;";
    laterBtn.onclick = () => bar.remove();

    bar.append(label, restartBtn, laterBtn);
    return bar;
  }

  Backend.on("update_ready", (data) => {
    if (document.getElementById("update-banner")) return; // already showing
    document.body.appendChild(buildBanner(data.version));
  });
})();
