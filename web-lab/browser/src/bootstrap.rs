//! Injected JavaScript: the telemetry bootstrap and the eval/cookie/storage snippets.
//!
//! The bootstrap is registered as an initialization script, so it runs **before any
//! page script on every navigation**. All observations travel to the engine through
//! the wry IPC bridge as `{type, payload}` JSON messages.

/// The default telemetry bootstrap: console capture, error capture and fetch/XHR
/// wrapping, plus small helpers (`window.__weblab`) for cookies and storage.
pub const BOOTSTRAP_JS: &str = r#"(function () {
  if (window.__weblab) { return; }
  var send = function (type, payload) {
    try {
      var bridge = window.ipc || ((window.webkit || {}).messageHandlers || {}).ipc;
      if (bridge && bridge.postMessage) {
        bridge.postMessage(JSON.stringify({ type: type, payload: payload }));
      }
    } catch (e) { /* the bridge is best-effort by design */ }
  };
  var clip = function (value) {
    try {
      var text = typeof value === 'string' ? value : JSON.stringify(value);
      if (text && text.length > 8192) { text = text.slice(0, 8192) + '…[truncated]'; }
      return text;
    } catch (e) { return String(value); }
  };
  window.__weblab = {
    version: 1,
    report: function (type, payload) { send(type, payload); },
    cookies: function () { return document.cookie; },
    storage: function () {
      var snapshot = { local: {}, session: {} };
      try {
        for (var i = 0; i < localStorage.length; i++) {
          var k = localStorage.key(i); snapshot.local[k] = clip(localStorage.getItem(k));
        }
      } catch (e) { snapshot.localError = String(e); }
      try {
        for (var j = 0; j < sessionStorage.length; j++) {
          var s = sessionStorage.key(j); snapshot.session[s] = clip(sessionStorage.getItem(s));
        }
      } catch (e) { snapshot.sessionError = String(e); }
      return snapshot;
    }
  };
  ['log', 'info', 'warn', 'error', 'debug'].forEach(function (level) {
    var original = console[level] ? console[level].bind(console) : function () {};
    console[level] = function () {
      var parts = [];
      for (var i = 0; i < arguments.length; i++) { parts.push(typeof arguments[i] === 'string' ? arguments[i] : clip(arguments[i])); }
      send('console', { level: level, text: parts.join(' ') });
      original.apply(null, arguments);
    };
  });
  window.addEventListener('error', function (event) {
    send('error', { message: clip(event.message), source: event.filename, line: event.lineno, column: event.colno });
  });
  window.addEventListener('unhandledrejection', function (event) {
    send('error', { message: 'Unhandled rejection: ' + clip(event.reason) });
  });
  var timing = function (start) { return Math.round(performance.now() - start); };
  var originalFetch = window.fetch;
  if (originalFetch) {
    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || String(input);
      var method = (init && init.method) || (input && input.method) || 'GET';
      var start = performance.now();
      return originalFetch.call(window, input, init).then(function (response) {
        send('network', { kind: 'fetch', url: clip(String(url)), method: method, status: response.status, ms: timing(start) });
        return response;
      }, function (error) {
        send('network', { kind: 'fetch', url: clip(String(url)), method: method, error: clip(String(error)), ms: timing(start) });
        throw error;
      });
    };
  }
  var originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__weblab = { method: String(method), url: clip(String(url)), start: performance.now() };
    return originalOpen.apply(this, arguments);
  };
  var reportXhr = function (failed) {
    if (!this.__weblab || this.__weblab.reported) { return; }
    this.__weblab.reported = true;
    send('network', {
      kind: 'xhr', url: this.__weblab.url, method: this.__weblab.method,
      status: failed ? 0 : this.status, ms: timing(this.__weblab.start), error: failed ? 'network error' : undefined
    });
  };
  XMLHttpRequest.prototype.addEventListener('load', function () { reportXhr.call(this, false); });
  XMLHttpRequest.prototype.addEventListener('error', function () { reportXhr.call(this, true); });
  window.__weblab.captureBodies = false;
  send('injected', { href: String(location.href), readyState: document.readyState });
})();
"#;

/// Wraps arbitrary code so the engine receives its result (or error) through the
/// bridge. Self-contained on purpose: it must work even when the bootstrap did not
/// run (for example on `about:blank`).
pub fn eval_wrapper(eval_id: &str, code: &str) -> String {
    format!(
        r#"(function () {{
  var send = function (type, payload) {{
    try {{
      var bridge = window.ipc || ((window.webkit || {{}}).messageHandlers || {{}}).ipc;
      if (bridge && bridge.postMessage) {{
        bridge.postMessage(JSON.stringify({{ type: type, payload: payload }}));
      }}
    }} catch (e) {{ }}
  }};
  Promise.resolve().then(function () {{
    try {{
      var result = (function () {{ {code} }})();
      var value;
      try {{ value = (typeof result === 'object' && result !== null) ? JSON.stringify(result) : String(result); }}
      catch (e) {{ value = String(result); }}
      if (typeof value === 'string' && value.length > 8192) {{ value = value.slice(0, 8192) + '…[truncated]'; }}
      send('eval-result', {{ evalId: '{eval_id}', ok: true, value: value }});
    }} catch (error) {{
      send('eval-result', {{ evalId: '{eval_id}', ok: false, error: String(error) }});
    }}
  }});
}})();"#
    )
}

/// Reads JS-visible cookies through the bridge (`document.cookie`; HttpOnly cookies
/// are deliberately out of reach of this layer).
pub fn cookie_reader(eval_id: &str) -> String {
    eval_wrapper(
        eval_id,
        r#"return { href: String(location.href), cookie: document.cookie };"#,
    )
}

/// Snapshots localStorage/sessionStorage through the bootstrap helper when present,
/// falling back to a plain read otherwise.
pub fn storage_reader(eval_id: &str) -> String {
    eval_wrapper(
        eval_id,
        r#"return window.__weblab ? window.__weblab.storage() : { error: 'bootstrap not present' };"#,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bootstrap_declares_bridge_and_capture_hooks() {
        assert!(BOOTSTRAP_JS.contains("window.ipc"));
        assert!(BOOTSTRAP_JS.contains("'console'"));
        assert!(BOOTSTRAP_JS.contains("unhandledrejection"));
        assert!(BOOTSTRAP_JS.contains("originalFetch"));
        assert!(BOOTSTRAP_JS.contains("XMLHttpRequest.prototype.open"));
        assert!(BOOTSTRAP_JS.contains("__weblab"));
        assert!(BOOTSTRAP_JS.contains("'injected'"));
    }

    #[test]
    fn eval_wrapper_embeds_code_and_id() {
        let wrapped = eval_wrapper("ev-1", "return 6 * 7;");
        assert!(wrapped.contains("ev-1"));
        assert!(wrapped.contains("return 6 * 7;"));
        assert!(wrapped.contains("eval-result"));
        // The wrapper must be balanced JS: braces and parens.
        assert_eq!(wrapped.matches('{').count(), wrapped.matches('}').count());
        assert_eq!(wrapped.matches('(').count(), wrapped.matches(')').count());
    }

    #[test]
    fn cookie_and_storage_readers_wrap_code() {
        assert!(cookie_reader("c-1").contains("document.cookie"));
        assert!(storage_reader("s-1").contains("__weblab.storage()"));
    }
}
