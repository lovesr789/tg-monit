"use strict";
// 和 monitor.py 保持一條本機 WebSocket；收到網址就直接開分頁，省掉每次起 chrome.exe 的時間。
// MV3 背景程式閒置會被休眠：連線期間每 20 秒送 keepalive 讓它保持清醒（Chrome 116+），
// 萬一還是被停掉，chrome.alarms 每 30 秒喚醒一次重連；斷線期間 monitor.py 會自動改用 Popen。
const URL_WS = "ws://127.0.0.1:8765";
const ALLOWED = /^https:\/\/([a-z0-9-]+\.)*tixcraft\.com\//;
let ws = null;
let keepalive = null;
let retry = null;
const ocrRequests = new Map();
const attempts = new Map();
const progressStages = new Set(["page_start", "tickets_ready", "ocr_start", "captcha_filled", "manual_input", "ocr_failed", "submit_click"]);

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "progress") {
    if (!sender.tab || sender.frameId !== 0 || !ALLOWED.test(sender.url || "") ||
        !progressStages.has(message.stage) || !Number.isFinite(message.page_ms) || message.page_ms < 0) return;
    if (ws?.readyState === WebSocket.OPEN) {
      const attempt = attempts.get(sender.tab.id);
      const report = { type: "progress", stage: message.stage, page_ms: message.page_ms, url: sender.url };
      if (attempt) {
        report.total_ms = Math.max(0, Date.now() - attempt.receivedAt);
        report.tab_ms = Math.max(0, Date.now() - attempt.openStartedAt);
      }
      try { ws.send(JSON.stringify(report)); } catch { /* Keep ticket actions independent of diagnostics. */ }
    }
    sendResponse({ ok: true });
    return;
  }
  if (message.type !== "ocr") return;
  if (!sender.tab || !ALLOWED.test(sender.url || "")) {
    sendResponse({ error: "不支援此頁面" });
    return;
  }
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    sendResponse({ error: "請先啟動 start.bat，等待本機橋接連線" });
    connect();
    return;
  }
  if (typeof message.image !== "string" || message.image.length > 1400000) {
    sendResponse({ error: "驗證碼圖片過大" });
    return;
  }
  const id = crypto.randomUUID();
  const timer = setTimeout(() => {
    ocrRequests.delete(id);
    sendResponse({ error: "辨識逾時，請手動輸入或點圖片重試" });
  }, 15000);
  ocrRequests.set(id, { sendResponse, timer });
  try {
    ws.send(JSON.stringify({ type: "ocr", id, image: message.image }));
  } catch {
    clearTimeout(timer);
    ocrRequests.delete(id);
    sendResponse({ error: "本機辨識連線失敗" });
  }
  return true;
});

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  clearTimeout(retry);
  try {
    ws = new WebSocket(URL_WS);
  } catch {
    retry = setTimeout(connect, 2000);
    return;
  }
  ws.onopen = () => {
    clearInterval(keepalive);
    keepalive = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send("keepalive");
    }, 20000);
  };
  ws.onmessage = event => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    if (!msg || typeof msg !== "object") return;
    if (msg && msg.type === "ocr_result" && ocrRequests.has(msg.id)) {
      const request = ocrRequests.get(msg.id);
      clearTimeout(request.timer);
      ocrRequests.delete(msg.id);
      request.sendResponse({ text: msg.text, error: msg.error, strategy: msg.strategy });
      return;
    }
    // 只開拓元網址，就算有別的本機程式連上也不能叫它開任意網站
    if (msg.type === "open" && typeof msg.url === "string" && ALLOWED.test(msg.url)) {
      const openStartedAt = Date.now();
      const created = chrome.tabs.create({ url: msg.url, active: true });
      created?.then?.(tab => {
        if (!Number.isInteger(tab?.id)) return;
        attempts.set(tab.id, {
          openStartedAt,
          receivedAt: Number.isFinite(msg.received_at_ms) ? msg.received_at_ms : openStartedAt
        });
        // Bound memory even if many sold-out tabs are created over a long run.
        if (attempts.size > 200) attempts.delete(attempts.keys().next().value);
      }).catch(error => console.warn("購票助手：開啟分頁失敗", error));
    }
  };
  ws.onclose = () => {
    for (const request of ocrRequests.values()) {
      clearTimeout(request.timer);
      request.sendResponse({ error: "本機辨識連線中斷，請手動輸入或換圖重試" });
    }
    ocrRequests.clear();
    clearInterval(keepalive);
    ws = null;
    retry = setTimeout(connect, 2000);
  };
}

chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "reconnect") connect(); });
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
