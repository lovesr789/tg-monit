"use strict";
document.getElementById("version").textContent = `v${chrome.runtime.getManifest().version}`;
const form = document.getElementById("settings");
const quantity = document.getElementById("quantity");
const enabled = document.getElementById("enabled");
const autoCaptcha = document.getElementById("autoCaptcha");
const autoSubmit = document.getElementById("autoSubmit");
const status = document.getElementById("status");
chrome.storage.local.get({ quantity: 1, enabled: true, autoCaptcha: true, autoSubmit: true }).then(settings => {
  quantity.value = settings.quantity;
  enabled.checked = settings.enabled;
  autoCaptcha.checked = settings.autoCaptcha;
  autoSubmit.checked = settings.autoSubmit;
}).catch(() => { status.textContent = "無法讀取設定，請重新開啟擴充功能。"; });
form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  try {
    await chrome.storage.local.set({ quantity: Number(quantity.value), enabled: enabled.checked, autoCaptcha: autoCaptcha.checked, autoSubmit: autoSubmit.checked });
    status.textContent = "已儲存，開啟的購票頁也會立即套用。";
  } catch {
    status.textContent = "儲存失敗，請重試。";
  }
});
