// PENT-02 lab sample (clean). It saves a note in extension storage.
// This comment mentions eval( and fetch( on purpose: the scanner must ignore
// comments and strings, so this file has to stay at 0 findings.
const box = document.getElementById("note");
const hint = "never use eval() here";

chrome.storage.local.get("note", (data) => {
  box.value = data.note || "";
});

box.addEventListener("input", () => {
  chrome.storage.local.set({ note: box.value });
});
