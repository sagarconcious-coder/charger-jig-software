(function () {
  let parameters = [];

  function render() {
    document.getElementById("page-configuration").innerHTML = `
      <div class="page-header">
        <div><h1>Configuration</h1><div class="page-sub">Test parameter tolerances</div></div>
      </div>

      <div class="card card-pad" style="margin-bottom:16px;">
        <h3 style="margin:0 0 12px;font-size:13px;">SERVER</h3>
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;">
          <div class="field" style="min-width:280px;flex:1;margin-bottom:0;">
            <label>Server Base URL</label>
            <input type="text" id="cfgServerUrl" placeholder="http://localhost:8000" />
          </div>
          <div class="field" style="min-width:200px;margin-bottom:0;">
            <label>Email</label>
            <input type="text" id="cfgServerEmail" placeholder="user@example.com" />
          </div>
          <div class="field" style="min-width:180px;margin-bottom:0;">
            <label>Password</label>
            <input type="password" id="cfgServerPassword" placeholder="Leave blank to keep existing" />
          </div>
          <button class="btn btn-primary btn-sm" id="cfgSaveServerBtn">${icon("check_circle", 13)} Save</button>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3>TEST PARAMETERS / TOLERANCES</h3>
          <button class="btn btn-primary btn-sm" id="cfgSaveParamsBtn">${icon("check_circle", 13)} Save Changes</button>
        </div>
        <div class="table-scroll" style="max-height:calc(100vh - 460px);">
          <table class="data-table">
            <thead><tr><th>Parameter</th><th>Unit</th><th>Expected</th><th>Tolerance</th></tr></thead>
            <tbody id="cfgParamBody"></tbody>
          </table>
        </div>
      </div>

      <div class="modal-overlay" id="cfgPasswordOverlay" style="display:none;">
        <div class="modal-card card card-pad">
          <h3 style="margin:0 0 12px;font-size:13px;">CONFIGURATION PASSWORD REQUIRED</h3>
          <div class="field">
            <label>Password</label>
            <input type="password" id="cfgPasswordInput" placeholder="Enter configuration password" />
          </div>
          <div id="cfgPasswordError" style="color:#ff8a8a;font-size:11.5px;margin-bottom:10px;display:none;">Incorrect password</div>
          <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button class="btn btn-ghost btn-sm" id="cfgPasswordCancelBtn">Cancel</button>
            <button class="btn btn-primary btn-sm" id="cfgPasswordConfirmBtn">${icon("check_circle", 13)} Confirm</button>
          </div>
        </div>
      </div>
    `;

    document.getElementById("cfgSaveParamsBtn").addEventListener("click", onSaveParamsClicked);
    document.getElementById("cfgSaveServerBtn").addEventListener("click", onSaveServerConfig);
    document.getElementById("cfgPasswordCancelBtn").addEventListener("click", closePasswordModal);
    document.getElementById("cfgPasswordConfirmBtn").addEventListener("click", onConfirmPassword);
    document.getElementById("cfgPasswordInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") onConfirmPassword();
    });
  }

  // 4.8: expected/tolerance changes are password-protected. Save is deferred
  // until the password is verified server-side.
  function onSaveParamsClicked() {
    const overlay = document.getElementById("cfgPasswordOverlay");
    const input = document.getElementById("cfgPasswordInput");
    const error = document.getElementById("cfgPasswordError");
    input.value = "";
    error.style.display = "none";
    overlay.style.display = "flex";
    input.focus();
  }

  function closePasswordModal() {
    document.getElementById("cfgPasswordOverlay").style.display = "none";
  }

  async function onConfirmPassword() {
    const password = document.getElementById("cfgPasswordInput").value;
    const res = await Backend.api().verify_config_password(password);
    if (!res.ok) {
      document.getElementById("cfgPasswordError").style.display = "block";
      return;
    }
    closePasswordModal();
    await onSaveParams();
  }

  async function onSaveServerConfig() {
    const url = document.getElementById("cfgServerUrl").value.trim();
    const email = document.getElementById("cfgServerEmail").value.trim();
    const password = document.getElementById("cfgServerPassword").value;
    const res = await Backend.api().save_server_config(url, email, password);
    document.getElementById("cfgServerPassword").value = "";
    if (res.ok) App.toast("Server settings saved", "success");
  }

  async function onSaveParams() {
    const updates = parameters.map((p) => ({
      name: p.name,
      expected_value: p.expected_value,
      tolerance: p.tolerance,
    }));
    parameters = await Backend.api().update_parameters(updates);
    renderParams();
    App.toast("Parameters saved", "success");
  }

  function renderParams() {
    const body = document.getElementById("cfgParamBody");
    if (!body) return;
    body.innerHTML = parameters
      .map(
        (p, i) => `<tr>
        <td>${p.name}</td><td>${p.unit}</td>
        <td><input type="number" step="0.001" value="${p.expected_value}" data-idx="${i}" class="cfg-expected" style="width:110px;background:var(--bg-input);border:1px solid var(--border);border-radius:6px;padding:5px 8px;color:var(--text-primary);"></td>
        <td><input type="number" step="0.001" value="${p.tolerance}" data-idx="${i}" class="cfg-tolerance" style="width:110px;background:var(--bg-input);border:1px solid var(--border);border-radius:6px;padding:5px 8px;color:var(--text-primary);"></td>
      </tr>`
      )
      .join("");

    body.querySelectorAll(".cfg-expected").forEach((el) =>
      el.addEventListener("change", (e) => {
        parameters[e.target.dataset.idx].expected_value = parseFloat(e.target.value);
      })
    );
    body.querySelectorAll(".cfg-tolerance").forEach((el) =>
      el.addEventListener("change", (e) => {
        parameters[e.target.dataset.idx].tolerance = parseFloat(e.target.value);
      })
    );
  }

  window.Pages = window.Pages || {};
  window.Pages.configuration = {
    async onInit() {
      render();
      parameters = await Backend.api().get_parameters();
      renderParams();

      const serverCfg = await Backend.api().get_server_config();
      document.getElementById("cfgServerUrl").value = serverCfg.base_url || "";
      document.getElementById("cfgServerEmail").value = serverCfg.email || "";
    },
    onShow() {},
  };
})();
