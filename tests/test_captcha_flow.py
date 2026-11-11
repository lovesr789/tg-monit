"""Exercise captcha prefill and ticket-form submission using local browser fixtures."""
import json
import re
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


BASE = Path(__file__).resolve().parents[1]
CHROME = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"


@unittest.skipUnless(CHROME.exists(), "Chrome is required for DOM verification")
class CaptchaFlowTest(unittest.TestCase):
    def test_local_progress_timing(self):
        source = (BASE / "chrome-extension/background.js").read_text(encoding="utf-8")
        timing = (BASE / "chrome-extension/timing.js").read_text(encoding="utf-8")
        fixture = r'''<!doctype html><meta charset="utf-8"><body><script>
let listener, socket, sent = [];
class FakeSocket {
  static OPEN = 1; static CONNECTING = 0;
  constructor() { this.readyState = 0; socket = this; }
  send(data) { sent.push(JSON.parse(data)); }
}
window.WebSocket = FakeSocket;
const sender = { tab: { id: 42 }, frameId: 0, url: 'https://tixcraft.com/ticket/ticket/test' };
window.chrome = {
  runtime: {
    onMessage: { addListener: fn => { listener = fn; } },
    onStartup: { addListener() {} }, onInstalled: { addListener() {} },
    sendMessage: async message => { listener(message, sender, () => {}); }
  },
  alarms: { create() {}, onAlarm: { addListener() {} } },
  tabs: { create: async () => ({ id: 42 }) }
};
</script><script>BACKGROUND</script><script>
(async () => {
  function check(value, name) { if (!value) throw Error(name); }
  socket.readyState = 1; socket.onopen();
  socket.onmessage({ data: JSON.stringify({ type: 'open', url: sender.url, received_at_ms: Date.now() - 100 }) });
  await Promise.resolve();
  const script = document.createElement('script'); script.textContent = TIMING; document.body.append(script);
  check(sent.length === 1 && sent[0].stage === 'page_start', 'document start diagnostic');
  check(sent[0].total_ms >= 100 && sent[0].page_ms >= 0, 'correlate notification and page timing');
  TicketTiming.mark('page_start');
  check(sent.length === 1, 'deduplicate one-time stages');
  TicketTiming.mark('ocr_start', false); TicketTiming.mark('ocr_start', false);
  check(sent.length === 3, 'record individual recognition attempts');
  listener({ type: 'progress', stage: 'invalid', page_ms: 0 }, sender, () => {});
  listener({ type: 'progress', stage: 'ocr_start', page_ms: -1 }, sender, () => {});
  listener({ type: 'progress', stage: 'ocr_start', page_ms: 2 }, { ...sender, url: 'https://example.com/' }, () => {});
  check(sent.length === 3, 'ignore invalid diagnostics');
  chrome.runtime.sendMessage = () => { throw Error('extension reloaded'); };
  TicketTiming.mark('submit_click');
  check(sent.every(item => !('image' in item) && !('text' in item)), 'omit captcha text and image');
  document.body.dataset.testResult = 'passed';
})().catch(error => { document.body.dataset.testResult = error.message; });
</script>'''.replace("BACKGROUND", source).replace("TIMING", json.dumps(timing))
        self.run_browser_fixture(fixture)

    def test_sold_out_alert_bridge(self):
        hook = (BASE / "chrome-extension/sold-out-alert.js").read_text(encoding="utf-8")
        bridge = (BASE / "chrome-extension/sold-out-bridge.js").read_text(encoding="utf-8")
        fixture = r'''<!doctype html><meta charset="utf-8"><body>
<script>
let alerts = [], closeRequests = [];
window.alert = message => alerts.push(message);
window.chrome = { runtime: { sendMessage: async message => { closeRequests.push(message); return { closed: true }; } } };
</script>SCRIPTS<script>
(async () => {
  const delay = () => new Promise(resolve => setTimeout(resolve, 100));
  function check(value, name) { if (!value) throw Error(name); }
  window.alert('驗證碼錯誤');
  window.alert('請先登入');
  await delay();
  check(alerts.length === 2, 'preserve other native alerts');
  check(closeRequests.length === BEFORE, 'only close sold-out alert');
  // A sold-out row in an otherwise available event listing must not close the tab.
  const row = document.createElement('div'); row.textContent = '此場次/區域已售完'; document.body.append(row);
  await delay(); check(closeRequests.length === BEFORE, 'ignore ordinary page text');
  window.alert(' 此場次 ／ 區域已售完。 ');
  await delay(); check(closeRequests.length === 1, 'close sold-out tab once');
  window.alert('此場次/區域已售完');
  await delay(); check(closeRequests.length === 1, 'ignore duplicate signal');
  check(alerts.length === 2, 'no blocking sold-out alert');
  check(closeRequests[0].type === 'close_sold_out', 'runtime close request');
  document.body.dataset.testResult = 'passed';
})().catch(error => { document.body.dataset.testResult = error.message; });
</script>'''
        for late_bridge in (False, True):
            with self.subTest(late_bridge=late_bridge):
                if late_bridge:
                    scripts = f"<script>{hook}</script><script>alert('此場次/區域已售完');</script><script>{bridge}</script>"
                else:
                    scripts = f"<script>{bridge}</script><script>{hook}</script>"
                self.run_browser_fixture(fixture.replace("SCRIPTS", scripts).replace("BEFORE", "1" if late_bridge else "0"))

    def test_background_closes_only_sending_sold_out_tab(self):
        source = (BASE / "chrome-extension/background.js").read_text(encoding="utf-8")
        fixture = r'''<!doctype html><meta charset="utf-8"><body><script>
let listener, removed = [];
class FakeSocket { static OPEN = 1; static CONNECTING = 0; constructor() { this.readyState = 0; } }
window.WebSocket = FakeSocket;
window.chrome = {
  runtime: { onMessage: { addListener: fn => { listener = fn; } }, onStartup: { addListener() {} }, onInstalled: { addListener() {} } },
  alarms: { create() {}, onAlarm: { addListener() {} } },
  tabs: { remove: async id => { removed.push(id); } }
};
</script><script>BACKGROUND</script><script>
(async () => {
  function check(value, name) { if (!value) throw Error(name); }
  const message = { type: 'close_sold_out', message: '此場次/區域已售完', tabId: 999 };
  const sender = { tab: { id: 42 }, frameId: 0, url: 'https://tixcraft.com/activity/game/26_btskns' };
  let result;
  check(listener(message, sender, value => { result = value; }) === true, 'asynchronous close response');
  await Promise.resolve();
  check(result.closed && removed.length === 1 && removed[0] === 42, 'use sending tab id only');
  for (const invalidSender of [
    { ...sender, frameId: 1 }, { ...sender, url: 'https://example.com/ticket/test' },
    { ...sender, url: 'https://tixcraft.com.evil.example/ticket/test' },
    { ...sender, url: 'https://tixcraft.com/ticketing/checkout' },
    { ...sender, url: 'https://tixcraft.com/activity/detail/test' }, { ...sender, tab: undefined }
  ]) {
    let denied; listener(message, invalidSender, value => { denied = value; });
    check(denied.error, 'reject unrelated sender');
  }
  let denied; listener({ ...message, message: '驗證碼錯誤' }, sender, value => { denied = value; });
  check(denied.error && removed.length === 1, 'reject unrelated alerts');
  chrome.tabs.remove = async () => { throw new Error('tab unavailable'); };
  listener(message, sender, value => { result = value; });
  await Promise.resolve(); await Promise.resolve();
  check(result.error === 'tab unavailable', 'surface close failure');
  document.body.dataset.testResult = 'passed';
})().catch(error => { document.body.dataset.testResult = error.message; });
</script>'''.replace("BACKGROUND", source)
        self.run_browser_fixture(fixture)

    def test_auto_submit_ticket_form(self):
        scripts = "</script><script>".join(
            (BASE / "chrome-extension" / filename).read_text(encoding="utf-8")
            for filename in ("captcha.js", "content.js")
        )
        fixture = r'''<!doctype html><meta charset="utf-8">
<form id="ticket-form"><table><tr><td>單場票 600</td><td>
<select name="TicketForm[ticketPrice][0]" id="tickets"><option value="0">0</option><option value="1">1</option><option value="2">2</option></select>
</td></tr><tr><td>身障優惠 300</td><td>
<select name="TicketForm[ticketPrice][1]" id="discount"><option value="0">0</option><option value="1">1</option></select>
</td></tr></table>
<input id="TicketForm_verifyCode" required><input type="checkbox" id="TicketForm_agree" required>
<img id="TicketForm_verifyCode-image"><button type="submit" id="confirm">確認張數</button></form>
<form id="payment-form"><button type="submit">付款</button></form>
<script>
const scenario = SCENARIO;
let changed, requests = [], submissions = 0, payments = 0, clicks = 0;
document.getElementById('ticket-form').addEventListener('submit', e => { e.preventDefault(); submissions++; });
document.getElementById('payment-form').addEventListener('submit', e => { e.preventDefault(); payments++; });
document.getElementById('confirm').addEventListener('click', () => clicks++);
window.chrome = {
  storage: { local: { get: async defaults => ({ ...defaults, autoSubmit: scenario !== 'disabled' }) }, onChanged: { addListener: fn => { changed = fn; } } },
  runtime: { sendMessage: message => new Promise(resolve => requests.push({ message, resolve: value => resolve({ strategy: scenario === 'old-server' ? undefined : 'dual-normalized-v1', ...value }) })) }
};
</script><script>CONTENT_SCRIPTS</script><script>
const delay = () => new Promise(resolve => setTimeout(resolve, 150));
const input = document.getElementById('TicketForm_verifyCode');
function check(value, name) { if (!value) throw Error(scenario + ': ' + name); }
async function refresh(color) {
  const canvas = document.createElement('canvas'); canvas.width = 120; canvas.height = 80;
  canvas.getContext('2d').fillStyle = color; canvas.getContext('2d').fillRect(0, 0, 120, 80);
  document.querySelector('img').src = canvas.toDataURL(); await delay();
}
(async () => {
  await refresh('blue'); await delay();
  check(requests.length === 1, 'start recognition');
  if (scenario === 'edit') { input.value = 'mine'; input.dispatchEvent(new Event('input')); }
  if (scenario === 'quantity') document.getElementById('tickets').value = '2';
  if (scenario === 'discount') { document.getElementById('tickets').value = '0'; document.getElementById('discount').value = '1'; }
  if (scenario === 'unchecked') document.getElementById('TicketForm_agree').checked = false;
  if (scenario === 'button-disabled') document.getElementById('confirm').disabled = true;
  if (scenario === 'missing-button') document.getElementById('confirm').textContent = '付款';
  if (scenario === 'toggle-off') changed({ autoSubmit: { newValue: false } }, 'local');
  if (scenario === 'off') changed({ enabled: { newValue: false } }, 'local');
  requests[0].resolve(scenario === 'error' ? { error: 'failed OCR' } : { text: 'abcd' });
  await delay();
  const expected = scenario === 'enabled' || scenario === 'repeat' ? 1 : 0;
  check(submissions === expected && clicks === expected, 'only submit when ready and enabled');
  check(payments === 0, 'never click payment form');
  if (scenario === 'edit') check(input.value === 'mine', 'preserve manual edit');
  if (scenario === 'error' || scenario === 'off') check(input.value === '', 'no fill on error or disable');
  if (scenario === 'repeat') {
    await refresh('red'); check(requests.length === 2, 'recognize refreshed captcha');
    requests[1].resolve({ text: 'efgh' }); await delay();
    check(submissions === 1 && clicks === 1, 'one automatic submission per page');
  }
  document.body.dataset.testResult = 'passed';
})().catch(error => { document.body.dataset.testResult = error.message; });
</script>'''.replace("CONTENT_SCRIPTS", scripts)
        for scenario in ("enabled", "disabled", "error", "edit", "quantity", "discount", "unchecked", "button-disabled", "missing-button", "toggle-off", "off", "old-server", "repeat"):
            with self.subTest(scenario=scenario):
                self.run_browser_fixture(fixture.replace("SCENARIO", json.dumps(scenario)))

    def test_background_routes_ocr_replies(self):
        source = (BASE / "chrome-extension/background.js").read_text(encoding="utf-8")
        fixture = r'''<!doctype html><meta charset="utf-8"><body><script>
let listener, socket, sent = [], opened = [];
class FakeSocket {
  static OPEN = 1; static CONNECTING = 0;
  constructor() { this.readyState = 0; socket = this; }
  send(data) { sent.push(JSON.parse(data)); }
}
window.WebSocket = FakeSocket;
window.chrome = {
  runtime: { onMessage: { addListener: fn => { listener = fn; } },
    onStartup: { addListener() {} }, onInstalled: { addListener() {} } },
  alarms: { create() {}, onAlarm: { addListener() {} } },
  tabs: { create: options => opened.push(options.url) }
};
</script><script>BACKGROUND_SCRIPT</script><script>
function check(value, name) { if (!value) throw Error(name); }
try {
  const sender = { tab: { id: 1 }, url: 'https://tixcraft.com/ticket/ticket/test' };
  let offline;
  listener({ type: 'ocr', image: 'abc' }, sender, value => { offline = value; });
  check(offline.error && sent.length === 0, 'offline error');
  socket.readyState = 1; socket.onopen();
  let denied;
  listener({ type: 'ocr', image: 'abc' }, { tab: {}, url: 'https://example.com/' }, value => { denied = value; });
  check(denied.error && sent.length === 0, 'reject unrelated page');
  let first, second;
  check(listener({ type: 'ocr', image: 'abc' }, sender, value => { first = value; }) === true, 'async response channel');
  listener({ type: 'ocr', image: 'def' }, sender, value => { second = value; });
  check(sent.length === 2 && sent[0].id !== sent[1].id, 'distinct correlation ids');
  socket.onmessage({ data: JSON.stringify({ type: 'ocr_result', id: sent[1].id, text: 'efgh' }) });
  check(second.text === 'efgh' && first === undefined, 'out of order reply');
  socket.onmessage({ data: JSON.stringify({ type: 'ocr_result', id: sent[0].id, text: 'abcd' }) });
  check(first.text === 'abcd', 'correct matching reply');
  socket.onmessage({ data: 'null' });
  socket.onmessage({ data: JSON.stringify({ type: 'open', url: sender.url }) });
  check(opened.length === 1, 'keep existing open-tab bridge');
  let disconnected;
  listener({ type: 'ocr', image: 'ghi' }, sender, value => { disconnected = value; });
  socket.readyState = 3; socket.onclose();
  check(disconnected.error, 'complete pending callback on disconnect');
  document.body.dataset.testResult = 'passed';
} catch (error) { document.body.dataset.testResult = error.message; }
</script>'''.replace("BACKGROUND_SCRIPT", source)
        self.run_browser_fixture(fixture)

    def test_prefill_refresh_and_manual_edits(self):
        source = (BASE / "chrome-extension/captcha.js").read_text(encoding="utf-8")
        fixture = r'''<!doctype html><meta charset="utf-8">
<form><input id="TicketForm_verifyCode"><button>確認</button></form>
<img id="TicketForm_verifyCode-image"><div id="status"></div>
<script>
let requests = [], submissions = 0, changes = 0;
document.querySelector('form').addEventListener('submit', e => { e.preventDefault(); submissions++; });
window.chrome = { runtime: { sendMessage: message => new Promise(resolve => requests.push({ message, resolve: value => resolve({ strategy: 'dual-normalized-v1', ...value }) })) }};
</script><script>CONTENT_SCRIPT</script><script>
const delay = () => new Promise(resolve => setTimeout(resolve, 100));
const input = document.querySelector('input');
const image = document.querySelector('img');
const show = message => { document.getElementById('status').textContent = message; };
const update = () => TicketCaptcha.update(input, true, show);
input.addEventListener('change', () => changes++);
function check(value, name) { if (!value) throw Error(name); }
async function refresh(color) {
  const canvas = document.createElement('canvas'); canvas.width = 120; canvas.height = 80;
  canvas.getContext('2d').fillStyle = color; canvas.getContext('2d').fillRect(0, 0, 120, 80);
  image.src = canvas.toDataURL(); await delay(); update(); await delay();
}
(async () => {
  await refresh('blue');
  check(requests.length === 1, 'one request per image');
  check(requests[0].message.type === 'ocr' && requests[0].message.image.length > 0, 'capture image pixels');
  requests[0].resolve({ text: 'AbCd' }); await delay();
  check(input.value === 'abcd' && changes === 1, 'fill and dispatch change');
  check(submissions === 0, 'never submit');
  input.value = 'manual'; input.dispatchEvent(new Event('input')); update();
  await refresh('green');
  check(input.value === 'manual' && requests.length === 1, 'preserve manual text on refresh');
  input.value = ''; await refresh('red');
  check(requests.length === 2, 'retry new image');
  await refresh('orange');
  check(requests.length === 3, 'start refreshed image');
  requests[1].resolve({ text: 'xxxx' }); await delay();
  check(input.value === '', 'discard stale result');
  input.value = 'mine'; input.dispatchEvent(new Event('input'));
  requests[2].resolve({ text: 'yyyy' }); await delay();
  check(input.value === 'mine', 'never overwrite input during inference');
  input.value = ''; await refresh('purple');
  requests[3].resolve({ error: 'local service unavailable' }); await delay();
  check(input.value === '' && document.getElementById('status').textContent.includes('local service unavailable'), 'show failure and permit manual entry');
  update(); check(requests.length === 4, 'no retry loop');
  await refresh('black'); requests[4].resolve({ text: 'qwer' }); await delay();
  check(input.value === 'qwer', 'recover after refresh');
  image.dispatchEvent(new Event('load')); await delay();
  check(input.value === 'qwer' && requests.length === 5, 'ignore duplicate load for identical pixels');
  await refresh('white');
  check(input.value === '' && requests.length === 6, 'changed image discards old auto text');
  TicketCaptcha.stop(); requests[5].resolve({ text: 'zzzz' }); await delay();
  check(input.value === '' && submissions === 0, 'disable cancels in-flight fill');
  document.body.dataset.testResult = 'passed';
})().catch(error => { document.body.dataset.testResult = error.message; });
</script>'''.replace("CONTENT_SCRIPT", source)
        self.run_browser_fixture(fixture)

    def run_browser_fixture(self, fixture):
        with tempfile.TemporaryDirectory(prefix="tg-captcha-test-") as directory:
            root = Path(directory)
            page = root / "fixture.html"
            page.write_text(fixture, encoding="utf-8")
            result = subprocess.run(
                [str(CHROME), "--headless", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={root / 'profile'}", "--dump-dom",
                 "--virtual-time-budget=10000", page.as_uri()],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-1500:])
            status = re.search(r'data-test-result="([^"]*)"', result.stdout)
            self.assertIsNotNone(status, result.stdout[-500:])
            self.assertEqual(status.group(1), "passed")


if __name__ == "__main__":
    unittest.main()
