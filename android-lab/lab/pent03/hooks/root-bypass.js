/*
 * root-bypass.js
 * ------------------------------------------------------------------------
 * Bypasses: common root-detection checks that stop an app from running on a
 *   rooted/emulated lab device, so dynamic analysis can proceed. Covers:
 *     - File.exists() probes for su / Magisk / busybox paths
 *     - Runtime.exec("su" / "which su")
 *     - build-tag / "test-keys" checks (android.os.Build.TAGS)
 *     - RootBeer.isRooted() (and its individual checks) when present
 * Logs each neutralised check; modifies nothing else.
 *
 * Load it:
 *     frida -U -f com.securebank.mobile -l root-bypass.js --no-pause
 * frida-server must be running on the device.
 *
 * AUTHORIZATION ONLY. Lab-owned or written-authorization apps, isolated
 * emulator only.
 */
'use strict';

function log(msg) {
  console.log('[root-bypass] ' + msg);
}

var ROOT_PATHS = [
  '/system/app/Superuser.apk',
  '/sbin/su',
  '/system/bin/su',
  '/system/xbin/su',
  '/data/local/xbin/su',
  '/data/local/bin/su',
  '/system/sd/xbin/su',
  '/system/bin/failsafe/su',
  '/data/local/su',
  '/su/bin/su',
  '/system/xbin/busybox',
  '/sbin/magisk',
  '/data/adb/magisk',
];

Java.perform(function () {
  log('starting root-detection bypass (lab use only)');

  // 1. File.exists() for known su/magisk paths.
  //    Keep the original overload reference and call *it* for non-root paths so
  //    we return the real answer without re-entering (and recursing into) the hook.
  try {
    var File = Java.use('java.io.File');
    var fileExists = File.exists.overload();
    fileExists.implementation = function () {
      var path = this.getAbsolutePath();
      if (ROOT_PATHS.indexOf(path) !== -1) {
        log('File.exists(' + path + ') -> false');
        return false;
      }
      return fileExists.call(this);
    };
    log('hooked java.io.File.exists');
  } catch (e) {
    log('File.exists hook skipped: ' + e);
  }

  // Only block the exact root-probe commands, so legitimate commands that merely
  // contain the letters "su"/"which" (e.g. "sudoku", "lsusb") run untouched.
  function isRootCommand(cmd) {
    if (!cmd) return false;
    var c = ('' + cmd).trim();
    var base = c.split(/\s+/)[0];
    var leaf = base.substring(base.lastIndexOf('/') + 1);
    if (leaf === 'su' || leaf === 'magisk' || leaf === 'busybox') return true;
    // "which su" / "command -v su" style probes
    return /\b(which|command\s+-v)\s+su\b/.test(c);
  }

  // 2. Runtime.exec — cover BOTH the String and String[] overloads; the array
  //    overload previously slipped past the filter entirely.
  try {
    var Runtime = Java.use('java.lang.Runtime');

    var execStr = Runtime.exec.overload('java.lang.String');
    execStr.implementation = function (cmd) {
      if (isRootCommand(cmd)) {
        log('Runtime.exec("' + cmd + '") -> blocked');
        return execStr.call(this, 'echo');
      }
      return execStr.call(this, cmd);
    };

    var execArr = Runtime.exec.overload('[Ljava.lang.String;');
    execArr.implementation = function (cmdArr) {
      var first = cmdArr && cmdArr.length ? cmdArr[0] : '';
      var joined = cmdArr ? Array.prototype.join.call(cmdArr, ' ') : '';
      if (isRootCommand(first) || isRootCommand(joined)) {
        log('Runtime.exec([' + joined + ']) -> blocked');
        return execStr.call(this, 'echo');
      }
      return execArr.call(this, cmdArr);
    };

    log('hooked Runtime.exec (String + String[])');
  } catch (e) {
    log('Runtime.exec hook skipped: ' + e);
  }

  // 3. Build.TAGS "test-keys".
  try {
    var Build = Java.use('android.os.Build');
    Build.TAGS.value = 'release-keys';
    log('set Build.TAGS -> release-keys');
  } catch (e) {
    /* field may be final on some runtimes */
  }

  // 4. RootBeer — neutralise the aggregate AND the individual checks it exposes,
  //    since apps often call the granular methods directly.
  try {
    var RootBeer = Java.use('com.scottyab.rootbeer.RootBeer');
    var falseMethods = [
      'isRooted', 'isRootedWithoutBusyBoxCheck', 'checkForBusyBoxBinary',
      'checkForSuBinary', 'checkForRWPaths', 'checkForDangerousProps',
      'checkForRootNative', 'detectRootManagementApps', 'detectPotentiallyDangerousApps',
      'detectTestKeys', 'checkForMagiskBinary', 'checkSuExists',
    ];
    falseMethods.forEach(function (name) {
      if (RootBeer[name]) {
        try {
          RootBeer[name].overloads.forEach(function (ov) {
            ov.implementation = function () {
              log('RootBeer.' + name + ' -> false');
              return false;
            };
          });
        } catch (inner) { /* some overloads can't be hooked; skip */ }
      }
    });
    log('hooked RootBeer (aggregate + individual checks)');
  } catch (e) {
    /* RootBeer not bundled */
  }

  log('root-detection checks neutralised');
});
