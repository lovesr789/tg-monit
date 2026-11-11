"use strict";
// Runs in MAIN at document_start, before the site's inline alert can block the tab.
(() => {
  const originalAlert = window.alert;
  window.alert = function (message) {
    const text = String(message).replace(/\s+/g, "").replace(/[。.!！]+$/, "");
    if (/^此(?:場次[\/／]區域|場次|區域)已售完$/.test(text)) {
      // Leave evidence for an isolated-world listener even if it starts later.
      const announce = () => {
        if (!document.documentElement) return false;
        document.documentElement.setAttribute("data-tg-ticket-sold-out", text);
        window.dispatchEvent(new Event("tg-ticket-sold-out"));
        return true;
      };
      if (!announce()) {
        const observer = new MutationObserver(() => { if (announce()) observer.disconnect(); });
        observer.observe(document, { childList: true });
      }
      return;
    }
    return originalAlert.apply(this, arguments);
  };
})();
