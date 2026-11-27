/*
 * ssl-pinning-universal.js
 * ------------------------------------------------------------------------
 * Bypasses: certificate / public-key pinning across the common Android TLS
 *   stacks so lab traffic can be read through mitmproxy. Covers:
 *     - javax.net.ssl X509TrustManager / TrustManagerImpl (AOSP, Conscrypt)
 *     - OkHttp3 CertificatePinner.check()
 *     - Android Network Security Config (NetworkSecurityTrustManager)
 *     - WebViewClient.onReceivedSslError
 *     - HostnameVerifier (HttpsURLConnection)
 * Traces nothing; it only neutralises pin checks (logs each neutralised site).
 *
 * Load it:
 *     frida -U -f com.securebank.mobile -l ssl-pinning-universal.js --no-pause
 * or via objection's custom-script option. frida-server must be running.
 *
 * AUTHORIZATION ONLY. Run exclusively against apps you own or are authorized
 * in writing to assess, on an isolated lab emulator. The scope guard in
 * scripts/scope.py gates the automated pipeline; this file is the hook it uses.
 */
'use strict';

function log(msg) {
  console.log('[unpin] ' + msg);
}

function hookTrustManagerImpl() {
  try {
    var TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
    // verifyChain returns the trusted chain; returning the input accepts it.
    TMI.verifyChain.implementation = function (certs, host) {
      log('TrustManagerImpl.verifyChain -> accepted ' + host);
      return certs;
    };
    log('hooked Conscrypt TrustManagerImpl.verifyChain');
  } catch (e) {
    /* class absent on this app/runtime */
  }
}

function hookX509TrustManager() {
  try {
    var SSLContext = Java.use('javax.net.ssl.SSLContext');
    var TrustManager = Java.registerClass({
      name: 'org.oslab.lab.TrustAllManager',
      implements: [Java.use('javax.net.ssl.X509TrustManager')],
      methods: {
        checkClientTrusted: function () {},
        checkServerTrusted: function () {},
        getAcceptedIssuers: function () {
          return Java.array('java.security.cert.X509Certificate', []);
        },
      },
    });
    var tms = [TrustManager.$new()];
    var init = SSLContext.init.overload(
      '[Ljavax.net.ssl.KeyManager;',
      '[Ljavax.net.ssl.TrustManager;',
      'java.security.SecureRandom'
    );
    init.implementation = function (km, tm, sr) {
      log('SSLContext.init -> replaced TrustManager with trust-all');
      init.call(this, km, tms, sr);
    };
    log('hooked SSLContext.init');
  } catch (e) {
    log('SSLContext.init hook skipped: ' + e);
  }
}

function hookOkHttp() {
  try {
    var CertificatePinner = Java.use('okhttp3.CertificatePinner');
    CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation =
      function (host) {
        log('OkHttp CertificatePinner.check -> skipped ' + host);
      };
    log('hooked okhttp3.CertificatePinner.check');
  } catch (e) {
    /* OkHttp not present */
  }
}

function hookNetworkSecurityConfig() {
  try {
    var NSTM = Java.use(
      'android.security.net.config.NetworkSecurityTrustManager'
    );
    // This 3-arg overload returns List<X509Certificate> (the trusted chain).
    // Returning undefined breaks callers, so hand back the presented chain.
    var ArrayList = Java.use('java.util.ArrayList');
    NSTM.checkServerTrusted.overload(
      '[Ljava.security.cert.X509Certificate;',
      'java.lang.String',
      'java.lang.String'
    ).implementation = function (chain, authType, host) {
      log('NetworkSecurityConfig.checkServerTrusted -> accepted ' + host);
      var list = ArrayList.$new();
      for (var i = 0; chain && i < chain.length; i++) list.add(chain[i]);
      return list;
    };
    log('hooked NetworkSecurityTrustManager');
  } catch (e) {
    /* pre-N or not using NSC */
  }
}

function hookHostnameVerifier() {
  try {
    var HttpsURLConnection = Java.use('javax.net.ssl.HttpsURLConnection');
    var AllowAll = Java.registerClass({
      name: 'org.oslab.lab.AllowAllHostnames',
      implements: [Java.use('javax.net.ssl.HostnameVerifier')],
      methods: { verify: function () { return true; } },
    });
    HttpsURLConnection.setDefaultHostnameVerifier(AllowAll.$new());
    log('installed allow-all HostnameVerifier');
  } catch (e) {
    /* best effort */
  }
}

function hookWebView() {
  // Hook the base WebViewClient. This covers subclasses that call
  // super.onReceivedSslError(...). Subclasses that fully override it without
  // calling super dispatch to their own method, so we also sweep already-loaded
  // WebViewClient subclasses and hook their override directly (best effort).
  try {
    var WebViewClient = Java.use('android.webkit.WebViewClient');
    WebViewClient.onReceivedSslError.overloads.forEach(function (ov) {
      ov.implementation = function (view, handler, error) {
        log('WebViewClient.onReceivedSslError -> proceed');
        handler.proceed();
      };
    });
    log('hooked WebViewClient.onReceivedSslError');
  } catch (e) {
    /* no WebView pinning */
  }

  try {
    Java.enumerateLoadedClasses({
      onMatch: function (name) {
        if (!/webview|sslclient|webclient/i.test(name)) return;
        try {
          var Cls = Java.use(name);
          if (!Cls.onReceivedSslError) return;
          Cls.onReceivedSslError.overloads.forEach(function (ov) {
            ov.implementation = function (view, handler, error) {
              log('override ' + name + '.onReceivedSslError -> proceed');
              handler.proceed();
            };
          });
        } catch (inner) { /* not a hookable subclass; skip */ }
      },
      onComplete: function () {},
    });
  } catch (e) {
    /* class sweep unavailable; base hook still applies */
  }
}

Java.perform(function () {
  log('universal SSL unpinning starting (lab use only)');
  hookTrustManagerImpl();
  hookX509TrustManager();
  hookOkHttp();
  hookNetworkSecurityConfig();
  hookHostnameVerifier();
  hookWebView();
  log('all available pin checks neutralised');
});
