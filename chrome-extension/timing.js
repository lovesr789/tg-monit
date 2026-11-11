"use strict";
// Diagnostics stay on the existing local bridge; never include captcha contents.
globalThis.TicketTiming = (() => {
  const recorded = new Set();
  function mark(stage, once = true) {
    if (once && recorded.has(stage)) return;
    recorded.add(stage);
    try {
      chrome.runtime.sendMessage({ type: "progress", stage, page_ms: performance.now() }).catch(() => {});
    } catch { /* Diagnostics must never interrupt ticket operations. */ }
  }
  mark("page_start");
  return { mark };
})();
