/*
 * method-trace.js
 * ------------------------------------------------------------------------
 * Traces: every method of one or more Java classes at runtime — logs each
 *   call's arguments and return value. Use it to understand an app's crypto,
 *   auth or networking internals once pinning is bypassed. Modifies nothing.
 *
 * Pick the target class(es) with an environment-style constant below, or pass
 * them via frida's -P/--parameters as { "classes": ["com.app.Crypto"] }.
 *
 * Load it:
 *     frida -U -f com.securebank.mobile -l method-trace.js --no-pause \
 *           -P '{"classes":["com.securebank.mobile.net.ApiClient"]}'
 * frida-server must be running on the device.
 *
 * AUTHORIZATION ONLY. Lab-owned or written-authorization apps, isolated
 * emulator only.
 */
'use strict';

// Fallback targets if no -P parameters are supplied.
var DEFAULT_CLASSES = ['com.securebank.mobile.net.ApiClient'];

function log(msg) {
  console.log('[trace] ' + msg);
}

function describe(value) {
  try {
    if (value === null || value === undefined) return String(value);
    return value.toString();
  } catch (e) {
    return '<unprintable>';
  }
}

function traceClass(className) {
  var Clazz;
  try {
    Clazz = Java.use(className);
  } catch (e) {
    log('class not found: ' + className);
    return;
  }
  var methods = Clazz.class.getDeclaredMethods();
  var hooked = 0;
  methods.forEach(function (m) {
    var name = m.getName();
    var overloads = Clazz[name].overloads;
    overloads.forEach(function (ov) {
      try {
        ov.implementation = function () {
          var args = [].slice.call(arguments).map(describe).join(', ');
          log(className + '.' + name + '(' + args + ')');
          var ret = ov.apply(this, arguments);
          log('  = ' + describe(ret));
          return ret;
        };
        hooked++;
      } catch (e) {
        /* some synthetic/overloaded methods can't be hooked; skip */
      }
    });
  });
  log('hooked ' + hooked + ' method(s) on ' + className);
}

Java.perform(function () {
  var params =
    typeof parameters !== 'undefined' && parameters ? parameters : {};
  var classes =
    params.classes && params.classes.length ? params.classes : DEFAULT_CLASSES;
  log('method tracing starting (lab use only)');
  classes.forEach(traceClass);
  log('tracing active on ' + classes.length + ' class(es)');
});
