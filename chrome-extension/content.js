"use strict";
(() => {
  let settings = { quantity: 1, enabled: true, autoCaptcha: true, autoSubmit: true };
  let ready = false;
  let pending = false;
  const handled = new WeakSet();
  const handledAgreements = new WeakSet();
  const ticketSelector = 'select[name^="TicketForm[ticketPrice]"], select[id^="TicketForm_ticketPrice_"]';
  const specialTicket = /身[心障]|愛心|輪椅|陪同|敬老|長者|老人|學生|學童|兒童|軍警|優惠|會員|套票|團體|早鳥|優待/;
  let focusedCaptcha = null;
  let notice;
  let submitAttempted = false;

  function isRegularTicket(select) {
    const row = select.closest("tr");
    return !specialTicket.test(row ? row.textContent : (select.getAttribute("aria-label") || ""));
  }

  function submitTicketForm(captcha) {
    if (!settings.enabled || !settings.autoCaptcha || !settings.autoSubmit) return "購票助手：驗證碼已填入；自動確認張數已關閉，請自行按確認。";
    if (submitAttempted) return "購票助手：已嘗試確認張數一次，請依網站結果手動處理。";
    const form = captcha.form;
    if (!form || !/^[a-z]{4}$/.test(captcha.value)) return "購票助手：驗證碼或購票表單不完整，請手動確認。";
    const selected = [...form.querySelectorAll(ticketSelector)].filter(select => Number(select.value) > 0);
    const regular = [...form.querySelectorAll(ticketSelector)].filter(select => visible(select) && isRegularTicket(select));
    const agreement = form.querySelector('input[type="checkbox"]#TicketForm_agree, input[type="checkbox"][name="TicketForm[agree]"]');
    if (regular.length !== 1 || selected.length !== 1 || selected[0] !== regular[0] || selected[0].value !== String(settings.quantity) || !agreement?.checked || !form.checkValidity()) {
      return "購票助手：票數、同意欄位或表單內容有變動，請手動確認送出。";
    }
    const buttons = [...form.querySelectorAll('button, input[type="submit"], input[type="button"]')];
    const button = buttons.find(item => /^(確認張數|確認票數)$/.test((item.tagName === "INPUT" ? item.value : item.textContent).replace(/\s/g, "")) && visible(item));
    if (!button) return "購票助手：找不到可用的確認張數按鈕，請手動送出。";
    // Set before click: site handlers may synchronously replace the captcha/form.
    submitAttempted = true;
    globalThis.TicketTiming?.mark("submit_click");
    button.click();
    return "購票助手：已按確認張數，請查看網站結果；本頁不會重複自動送出。";
  }

  function show(message) {
    const version = chrome.runtime?.getManifest?.()?.version || "1.4.0";
    message = message.replace(/^購票助手：/, `購票助手 v${version}：`);
    if (!notice) {
      notice = document.createElement("div");
      notice.id = "tg-ticket-helper-status";
      notice.setAttribute("role", "status");
      notice.style.cssText = "position:fixed;bottom:16px;left:16px;z-index:2147483647;max-width:380px;padding:12px 16px;background:#153b32;color:white;border-radius:8px;font:14px/1.6 sans-serif;box-shadow:0 2px 12px #0004;pointer-events:none";
      document.body.append(notice);
    }
    // Avoid a MutationObserver loop caused by updating our own status node.
    if (notice.textContent !== message) notice.textContent = message;
  }

  function visible(element) {
    return !element.disabled && element.getClientRects().length > 0;
  }

  function scan() {
    if (!ready) return;
    if (!settings.enabled) {
      globalThis.TicketCaptcha?.stop();
      if (notice) notice.remove();
      notice = null;
      return;
    }
    const selects = [...document.querySelectorAll(ticketSelector)].filter(visible);
    if (!selects.length) {
      show(location.pathname.startsWith("/ticket/area/")
        ? "購票助手：請先選擇票區，進入購票頁後會自動選票。"
        : "購票助手：等待票數欄位；若需登入、選場次或驗證，請先完成頁面操作。");
      return;
    }
    // Exclude restricted/discount tickets using their own row, never page-wide text.
    const regular = selects.filter(isRegularTicket);
    if (regular.length !== 1) {
      show(regular.length
        ? "購票助手：此頁有多個一般票種，請手動選擇票種與張數，再輸入驗證碼。"
        : "購票助手：目前僅找到優惠或資格限定票，請手動確認票種與張數。");
      return;
    }
    const select = regular[0];
    if (selects.some(other => other !== select && Number(other.value) > 0)) {
      show("購票助手：已有其他票種被選取，請確認張數並手動完成購票。");
      return;
    }
    const desired = String(settings.quantity);
    if (!handled.has(select)) {
      const option = [...select.options].find(item => item.value === desired && !item.disabled && !item.parentElement.disabled);
      if (!option) {
        show(`購票助手：目前無法選擇 ${desired} 張，請確認剩餘票數或調整設定。`);
        return;
      }
      handled.add(select);
      select.value = desired;
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
      globalThis.TicketTiming?.mark("tickets_ready");
    }
    const agreement = document.querySelector('input[type="checkbox"]#TicketForm_agree, input[type="checkbox"][name="TicketForm[agree]"]');
    if (agreement && visible(agreement) && !handledAgreements.has(agreement)) {
      handledAgreements.add(agreement);
      if (!agreement.checked) agreement.click();
    }
    const captcha = document.querySelector('#TicketForm_verifyCode, input[name="TicketForm[verifyCode]"]');
    if (!captcha || !visible(captcha)) {
      show("購票助手：票數已處理，等待驗證碼欄位；若有其他驗證，請手動完成。");
      return;
    }
    if (focusedCaptcha !== captcha) {
      focusedCaptcha = captcha;
      if (!captcha.value) {
        captcha.focus();
        captcha.scrollIntoView({ block: "center", behavior: "instant" });
      }
    }
    if (globalThis.TicketCaptcha) {
      globalThis.TicketCaptcha.update(captcha, settings.autoCaptcha !== false, show, submitTicketForm);
      if (settings.autoCaptcha === false) show("購票助手：請手動輸入驗證碼，核對後自行送出。");
    } else {
      show("購票助手：請依圖片輸入驗證碼，確認票數與同意欄位後自行送出。");
    }
  }

  function schedule() {
    if (pending) return;
    pending = true;
    setTimeout(() => { pending = false; scan(); }, 0);
  }
  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ["disabled", "hidden", "style", "class", "value", "src"]
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.quantity) {
      settings.quantity = changes.quantity.newValue ?? 1;
      document.querySelectorAll(ticketSelector).forEach(select => handled.delete(select));
    }
    if (changes.enabled) settings.enabled = changes.enabled.newValue ?? true;
    if (changes.autoCaptcha) settings.autoCaptcha = changes.autoCaptcha.newValue ?? true;
    if (changes.autoSubmit) settings.autoSubmit = changes.autoSubmit.newValue ?? true;
    if (!settings.enabled || !settings.autoCaptcha) globalThis.TicketCaptcha?.stop();
    schedule();
  });
  chrome.storage.local.get(settings).then(saved => {
    settings = saved;
    if (!Number.isInteger(settings.quantity) || settings.quantity < 1 || settings.quantity > 20) settings.quantity = 1;
    ready = true;
    scan();
  }).catch(() => { show("購票助手：設定讀取失敗，請重新載入擴充功能與此頁。"); });
})();
