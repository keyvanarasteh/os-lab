// PENT-02 lab sample: content script that adds a hidden iframe to every page
// (injection pattern). The frame points to the local lab server only.
const frame = document.createElement("iframe");
frame.src = "http://127.0.0.1:8765/frame.html";
frame.style.display = "none";
document.body.appendChild(frame);
