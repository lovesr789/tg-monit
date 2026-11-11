"use strict";
// Read the displayed image; notify the ticket-page controller after a successful fill.
globalThis.TicketCaptcha = (() => {
  let active;
  let enabled = true;
  let showStatus;
  let afterFill;
  let sequence = 0;
  const automaticValues = new WeakMap();

  function imageBytes(image) {
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    canvas.getContext("2d").drawImage(image, 0, 0);
    return canvas.toDataURL("image/png").split(",")[1];
  }

  function invalidate() {
    sequence++;
    if (active && active.input.value === automaticValues.get(active.input)) {
      active.input.value = "";
      active.input.dispatchEvent(new Event("input", { bubbles: true }));
      active.input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    active = null;
  }

  function update(input, isEnabled, show, onFilled) {
    showStatus = show;
    if (onFilled !== undefined) afterFill = onFilled;
    enabled = isEnabled;
    if (!enabled) { sequence++; active = null; return; }
    const image = document.querySelector('#TicketForm_verifyCode-image, img[src*="/ticket/captcha"], img[id*="verifyCode"]');
    if (!image) { show("購票助手：找不到驗證碼圖片，請手動輸入。"); return; }
    const source = `${image.src}|${image.currentSrc}`;
    if (active && (active.image !== image || active.source !== source || active.input !== input)) invalidate();
    if (!image.complete || !image.naturalWidth) {
      show("購票助手：等待驗證碼圖片載入。");
      return;
    }
    if (active) {
      show(active.message);
      return;
    }
    if (input.value) {
      show("購票助手：已保留驗證碼，請核對後自行確認送出。");
      return;
    }
    const state = { image, source, input, message: "購票助手：正在本機辨識驗證碼…", sequence: ++sequence };
    active = state;
    globalThis.TicketTiming?.mark("ocr_start", false);
    show(state.message);
    const edit = () => { state.edited = true; };
    input.addEventListener("input", edit);
    (async () => {
      try {
        state.imageData = imageBytes(image);
        const response = await chrome.runtime.sendMessage({ type: "ocr", image: state.imageData });
        if (!enabled || active !== state || state.sequence !== sequence || !input.isConnected || !image.isConnected || `${image.src}|${image.currentSrc}` !== source) return;
        if (state.edited || input.value) {
          globalThis.TicketTiming?.mark("manual_input", false);
          state.message = "購票助手：已保留你輸入的驗證碼，請核對後自行確認送出。";
        } else if (response?.error || !/^[a-zA-Z]{4}$/.test(response?.text || "")) {
          throw new Error(response?.error || "辨識結果不完整，請手動輸入或點圖片換圖");
        } else if (response.strategy !== "dual-normalized-v1") {
          throw new Error("本機辨識程式仍為舊版，請關閉原監控視窗後重新啟動 start.bat");
        } else {
          input.removeEventListener("input", edit);
          input.value = response.text.toLowerCase();
          automaticValues.set(input, input.value);
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
          globalThis.TicketTiming?.mark("captcha_filled", false);
          state.message = "購票助手：驗證碼已填入，請核對圖片；可手動修改，由你按確認。";
          if (enabled && active === state && afterFill) {
            state.message = afterFill(input) || state.message;
          }
        }
      } catch (error) {
        if (active !== state || !enabled) return;
        globalThis.TicketTiming?.mark("ocr_failed", false);
        state.message = `購票助手：${error.message}；可手動輸入，或點圖片換圖重試。`;
      } finally {
        input.removeEventListener("input", edit);
      }
      if (active === state && enabled) showStatus(state.message);
    })();
  }

  document.addEventListener("load", event => {
    if (event.target.matches?.('#TicketForm_verifyCode-image, img[src*="/ticket/captcha"], img[id*="verifyCode"]')) {
      const input = document.querySelector('#TicketForm_verifyCode, input[name="TicketForm[verifyCode]"]');
      // A completed image can be scanned before its queued load event fires.
      // Do not restart inference for the identical pixels; a same-URL reload
      // with different pixels still invalidates the old answer below.
      if (active?.image === event.target && active.input === input) {
        try { if (active.imageData === imageBytes(event.target)) return; } catch { /* Retry normally. */ }
      }
      invalidate();
      if (input && showStatus) update(input, enabled, showStatus);
    }
  }, true);
  return { update, stop: () => { enabled = false; sequence++; active = null; } };
})();
