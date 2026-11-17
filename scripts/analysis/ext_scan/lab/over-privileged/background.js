// PENT-02 lab sample (over-privileged). The code only counts open tabs and
// shows the number on the badge; the risk comes from the manifest alone.
async function updateBadge() {
  const tabs = await chrome.tabs.query({});
  chrome.action.setBadgeText({ text: String(tabs.length) });
}

chrome.tabs.onCreated.addListener(updateBadge);
chrome.tabs.onRemoved.addListener(updateBadge);
updateBadge();
