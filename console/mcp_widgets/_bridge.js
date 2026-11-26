/* Shared MCP Apps / ChatGPT Apps bridge for os-lab cleanup widgets and apps.
 * Hosts post tool results; this bridge normalizes them onto window.__oslabUi.
 */
(function () {
  var state = { input: null, output: null, theme: "light" };
  var listeners = [];

  function notify() {
    listeners.forEach(function (fn) {
      try { fn(state); } catch (err) { console.error(err); }
    });
  }

  function applyTheme(theme) {
    state.theme = theme || state.theme;
    document.documentElement.dataset.theme = state.theme;
    document.documentElement.style.colorScheme = state.theme;
  }

  function ingest(payload) {
    if (!payload || typeof payload !== "object") return;
    if (payload.structuredContent != null) state.output = payload.structuredContent;
    else if (payload.result && payload.result.structuredContent != null) state.output = payload.result.structuredContent;
    else if (payload.toolOutput != null) state.output = payload.toolOutput;
    else if (payload.content && payload.content[0] && payload.content[0].text) {
      try { state.output = JSON.parse(payload.content[0].text); } catch (_) { state.output = payload; }
    } else if (payload.arguments != null) {
      state.input = payload.arguments;
    } else {
      state.output = payload;
    }
    if (payload.theme) applyTheme(payload.theme);
    notify();
  }

  window.__oslabUi = {
    getState: function () { return state; },
    onUpdate: function (fn) { listeners.push(fn); if (state.output || state.input) fn(state); },
    setOutput: function (value) { state.output = value; notify(); },
    bytes: function (n) {
      if (n == null || !isFinite(n)) return "—";
      var u = ["B", "KB", "MB", "GB", "TB"], i = 0, v = Number(n);
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
      return (i === 0 ? String(Math.round(v)) : v.toFixed(v >= 10 ? 0 : 1)) + " " + u[i];
    },
    callTool: function (name, args) {
      if (window.openai && typeof window.openai.callTool === "function") {
        return window.openai.callTool(name, args || {});
      }
      window.parent.postMessage({ jsonrpc: "2.0", method: "tools/call", params: { name: name, arguments: args || {} } }, "*");
      return Promise.resolve(null);
    }
  };

  window.addEventListener("message", function (event) {
    var data = event.data;
    if (!data) return;
    if (data.method === "ui/notifications/tool-result" || data.method === "ui/notifications/tool-input") {
      ingest(data.params || data);
      return;
    }
    if (data.type === "ui/notifications/tool-result" || data.type === "tool-result") {
      ingest(data.payload || data);
      return;
    }
    ingest(data);
  });

  if (window.openai) {
    if (window.openai.toolOutput) ingest({ toolOutput: window.openai.toolOutput });
    if (window.openai.toolInput) state.input = window.openai.toolInput;
    if (typeof window.openai.onToolOutput === "function") {
      window.openai.onToolOutput(function (out) { ingest({ toolOutput: out }); });
    }
  }

  applyTheme(document.documentElement.dataset.theme || "light");
})();
