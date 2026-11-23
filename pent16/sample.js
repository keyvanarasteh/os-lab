// PENT-16 Test Corpus - Browser Extension Security Scan
function auditExtensionCore() {
    // Risk 1: Dynamic code execution
    eval("console.log('Critical: eval execution found');");

    // Risk 2: Unsafe DOM manipulation
    document.getElementById("user-output").innerHTML = "<b>Warning: XSS Risk</b>";

    // Risk 3: Unsafe document writing
    document.write("<script>maliciousPayload()</script>");

    // Risk 4: Extension privileged script injection simulation
    chrome.tabs.executeScript(tab.id, {code: "alert('Injected Script');"});
}
