(function () {
  let parameters = [];

  function render() {
    document.getElementById("page-configuration").innerHTML = `
      <div class="page-header">
        <div><h1>Configuration</h1><div class="page-sub">Test parameter tolerances</div></div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3>TEST PARAMETERS / TOLERANCES</h3>
          <button class="btn btn-primary btn-sm" id="cfgSaveParamsBtn">${icon("check_circle", 13)} Save Changes</button>
        </div>
        <div class="table-scroll" style="max-height:calc(100vh - 340px);">
          <table class="data-table">
            <thead><tr><th>Parameter</th><th>Unit</th><th>Expected</th><th>Tolerance</th></tr></thead>
            <tbody id="cfgParamBody"></tbody>
          </table>
        </div>
      </div>
    `;

    document.getElementById("cfgSaveParamsBtn").addEventListener("click", onSaveParams);
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
    },
    onShow() {},
  };
})();
