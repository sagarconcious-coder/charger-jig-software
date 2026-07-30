// Thin wrapper around window.pywebview.api, plus the backend -> frontend
// event dispatcher that bridge.py's _push() calls into.

const Backend = {
  ready: false,
  _readyWaiters: [],

  async whenReady() {
    if (this.ready) return;
    return new Promise((resolve) => this._readyWaiters.push(resolve));
  },

  _markReady() {
    this.ready = true;
    this._readyWaiters.forEach((fn) => fn());
    this._readyWaiters = [];
  },

  api() {
    return window.pywebview.api;
  },
};

window.addEventListener("pywebviewready", () => Backend._markReady());

// Event bus: pages subscribe via Backend.on(event, handler)
const _listeners = {};
window.__onBackendEvent = function (event, data) {
  const handlers = _listeners[event];
  if (!handlers) return;
  for (const fn of handlers) {
    try {
      fn(data);
    } catch (err) {
      console.error(`handler for ${event} failed`, err);
    }
  }
};

Backend.on = function (event, fn) {
  (_listeners[event] = _listeners[event] || []).push(fn);
  return () => {
    _listeners[event] = _listeners[event].filter((f) => f !== fn);
  };
};
