"use strict";
(() => {
  let closing = false;
  function closeSoldOutTab() {
    const message = document.documentElement?.getAttribute("data-tg-ticket-sold-out");
    if (closing || !/^此(?:場次[\/／]區域|場次|區域)已售完$/.test(message || "")) return;
    closing = true;
    globalThis.TicketTiming?.mark("sold_out");
    chrome.runtime.sendMessage({ type: "close_sold_out", message }).then(response => {
      if (response?.error) {
        closing = false;
        console.warn("購票助手：售完分頁關閉失敗", response.error);
      }
    }).catch(error => {
      closing = false;
      console.warn("購票助手：請重新載入擴充功能與此頁", error);
    });
  }
  window.addEventListener("tg-ticket-sold-out", closeSoldOutTab);
  const observer = new MutationObserver(closeSoldOutTab);
  observer.observe(document, {
    subtree: true, childList: true, attributes: true,
    attributeFilter: ["data-tg-ticket-sold-out"]
  });
  closeSoldOutTab();
})();
