"""Use installed Chrome to exercise the content script against a local ticket form."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


BASE = Path(__file__).resolve().parents[1]
CHROME = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"


@unittest.skipUnless(CHROME.exists(), "Chrome is required for DOM verification")
class TicketHelperTest(unittest.TestCase):
    def test_ticket_flow(self):
        source = (BASE / "chrome-extension/content.js").read_text(encoding="utf-8")
        fixture = r'''<!doctype html><meta charset="utf-8">
<table><tbody><tr><td>身障優惠票 300</td><td>
<select name="TicketForm[ticketPrice][1]" id="discount">
<option value="0">0</option><option value="1">1</option></select>
</td><td>一位身障證明持有者與必要陪同者限一位亦享有半價優惠</td></tr>
<tr><td>單場票 600</td><td><select name="TicketForm[ticketPrice][0]" id="tickets">
<option value="0">0</option><option value="1">1</option><option value="2">2</option>
</select></td></tr></tbody></table>
<input id="TicketForm_verifyCode"><label><input type="checkbox" id="TicketForm_agree" name="TicketForm[agree]">我已詳細閱讀且同意</label>
<div id="dynamic"></div>
<script>
let changed;
window.chrome = { storage: {
  local: { get: async defaults => defaults },
  onChanged: { addListener: listener => { changed = listener; } }
}};
let inputEvents = 0, changeEvents = 0, agreementChanges = 0;
document.getElementById('tickets').addEventListener('input', () => inputEvents++);
document.getElementById('tickets').addEventListener('change', () => changeEvents++);
document.getElementById('TicketForm_agree').addEventListener('change', () => agreementChanges++);
</script><script>CONTENT_SCRIPT</script><script>
const delay = () => new Promise(resolve => setTimeout(resolve, 180));
const results = [];
function check(condition, label) { if (!condition) throw Error(label); results.push(label); }
(async () => {
  await delay();
  let tickets = document.getElementById('tickets');
  const captcha = document.getElementById('TicketForm_verifyCode');
  const status = () => document.getElementById('tg-ticket-helper-status');
  check(tickets.value === '1', 'default quantity');
  check(document.getElementById('discount').value === '0', 'skip discount even when first row');
  check(document.getElementById('TicketForm_agree').checked && agreementChanges === 1, 'check agreement with change event');
  check(inputEvents === 1 && changeEvents === 1, 'dispatch input and change once');
  check(document.activeElement === captcha, 'focus captcha');
  tickets.value = '2';
  captcha.value = 'ABCD';
  document.getElementById('TicketForm_agree').checked = false;
  document.getElementById('dynamic').textContent = 'site update';
  await delay();
  check(tickets.value === '2' && captcha.value === 'ABCD', 'preserve manual edits');
  check(!document.getElementById('TicketForm_agree').checked && agreementChanges === 1, 'preserve manual uncheck');
  changed({ quantity: { newValue: 3 } }, 'local');
  await delay();
  check(tickets.value === '2' && status().textContent.includes('無法選擇 3 張'), 'no fallback for unavailable quantity');
  tickets.add(new Option('3', '3'));
  await delay();
  check(tickets.value === '3', 'retry after options arrive');
  changed({ enabled: { newValue: false } }, 'local');
  await delay();
  check(!status(), 'disable removes notice');
  changed({ enabled: { newValue: true } }, 'local');
  await delay();
  const replacement = tickets.cloneNode(true);
  replacement.value = '0';
  tickets.replaceWith(replacement);
  tickets = replacement;
  await delay();
  check(tickets.value === '3', 'handle replaced form');
  const extra = tickets.cloneNode(true);
  extra.id = 'other-price'; extra.value = '0'; document.body.append(extra);
  changed({ quantity: { newValue: 1 } }, 'local');
  await delay();
  check(extra.value === '0' && tickets.value === '3' && status().textContent.includes('多個一般票種'), 'multiple regular prices require manual choice');
  extra.remove();
  await delay();
  check(tickets.value === '1', 'apply updated preference');
  // Real pages can expose ticket fields by their id as well as their name.
  tickets.removeAttribute('name');
  tickets.id = 'TicketForm_ticketPrice_0';
  const idOnly = tickets.cloneNode(true); idOnly.value = '0'; tickets.replaceWith(idOnly); tickets = idOnly;
  await delay();
  check(tickets.value === '1', 'id selector fallback');
  const agreement = document.getElementById('TicketForm_agree');
  agreement.replaceWith(agreement.cloneNode(true));
  await delay();
  check(document.getElementById('TicketForm_agree').checked, 'check replacement agreement');
  document.getElementById('discount').value = '1';
  tickets.value = '0';
  changed({ quantity: { newValue: 2 } }, 'local');
  await delay();
  check(tickets.value === '0' && status().textContent.includes('已有其他票種'), 'preserve existing other-ticket choice');
  document.getElementById('discount').value = '0';
  tickets.closest('tr').remove();
  await delay();
  check(document.getElementById('discount').value === '0' && status().textContent.includes('資格限定票'), 'never auto select a discount-only row');
  document.body.dataset.testResult = 'passed';
  document.body.dataset.checks = results.length;
})().catch(error => { document.body.dataset.testResult = error.message; });
</script>'''.replace("CONTENT_SCRIPT", source)
        with tempfile.TemporaryDirectory(prefix="tg-ticket-test-") as directory:
            root = Path(directory)
            page = root / "fixture.html"
            page.write_text(fixture, encoding="utf-8")
            result = subprocess.run(
                [str(CHROME), "--headless", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={root / 'profile'}", "--dump-dom",
                 "--virtual-time-budget=5000", page.as_uri()],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertIn('data-test-result="passed"', result.stdout, result.stdout[-3000:])
            self.assertIn('data-checks="17"', result.stdout)

    def test_manifest_files_exist(self):
        extension = BASE / "chrome-extension"
        manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        for script in manifest["content_scripts"]:
            for filename in script["js"]:
                self.assertTrue((extension / filename).is_file())
        self.assertTrue((extension / manifest["action"]["default_popup"]).is_file())
        scripts = [filename for item in manifest["content_scripts"] for filename in item["js"]]
        self.assertNotIn("sold-out-alert.js", scripts)
        self.assertNotIn("sold-out-bridge.js", scripts)
        timing = next(item for item in manifest["content_scripts"] if "timing.js" in item["js"])
        self.assertEqual(timing["run_at"], "document_start")
        self.assertIn("https://tixcraft.com/activity/game/*", timing["matches"])



if __name__ == "__main__":
    unittest.main()
