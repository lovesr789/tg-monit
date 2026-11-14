"""監聽 Telegram 頻道，一收到通知就用指定的 Chrome 設定檔開啟訊息裡的連結。

開分頁有兩條路：
1. 擴充功能橋接（快）：chrome-extension 的背景程式透過本機 WebSocket 連進來，
   收到網址直接 chrome.tabs.create，不用另外起程序。
2. Popen 退路（慢 100–300ms）：擴充功能沒連上時，改用 chrome.exe 開網址。
"""
import asyncio
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl
from websockets.asyncio.server import serve
from captcha_ocr import ocr

BASE = Path(__file__).resolve().parent
CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))

if not CFG.get("api_id") or not CFG.get("api_hash"):
    sys.exit("請先在 config.yaml 填入 api_id / api_hash（https://my.telegram.org 申請）")

DOMAIN = CFG.get("link_domain", "tixcraft.com")
URL_RE = re.compile(r"https?://[^\s<>\"'）)]+")
CHROME = CFG["chrome_path"]
PROFILE = CFG.get("chrome_profile", "Default")
DEDUP = float(CFG.get("dedup_seconds", 5))
BRIDGE_PORT = int(CFG.get("bridge_port", 8765))

_last_opened: dict[str, float] = {}
_bridges: set = set()  # 已連上的擴充功能背景程式
_server = None


def log(*parts: object, timestamp: float | None = None) -> None:
    """Print a console entry with local time to the nearest second."""
    moment = datetime.now() if timestamp is None else datetime.fromtimestamp(timestamp)
    print(f"[{moment:%H:%M:%S}]", *parts, flush=True)


def extract_links(msg) -> list[str]:
    """從文字、超連結 entity、inline 按鈕裡找出目標網域的連結（保持順序、去重）。"""
    text = msg.raw_text or ""
    found: list[str] = []
    for ent in msg.entities or []:
        if isinstance(ent, MessageEntityTextUrl):
            found.append(ent.url)
    for _, t in msg.get_entities_text(MessageEntityUrl):
        found.append(t)
    found += URL_RE.findall(text)
    for row in msg.buttons or []:
        for b in row:
            if getattr(b, "url", None):
                found.append(b.url)

    out: list[str] = []
    for u in found:
        u = u.rstrip(".,;:!?、。")
        if DOMAIN in u and u not in out:
            out.append(u)
    # 優先開各區的購票頁（/ticket/ticket/），沒有才退回選區頁（Buy Now 的 /ticket/area/）
    direct = [u for u in out if "/ticket/ticket/" in u]
    return direct or out


def open_via_popen(url: str) -> None:
    subprocess.Popen(
        [CHROME, f"--profile-directory={PROFILE}", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def open_url(url: str, received_at: float | None = None) -> str:
    """優先走擴充功能；沒有連線或送出失敗就退回 Popen。回傳實際走的路。"""
    for ws in list(_bridges):
        try:
            await ws.send(json.dumps({"type": "open", "url": url, "received_at_ms": (received_at or time.time()) * 1000}))
            return "擴充"
        except Exception:
            _bridges.discard(ws)
    open_via_popen(url)
    return "Popen"


async def bridge_handler(ws):
    # 只接受 Chrome 擴充功能：一般網頁的 Origin 是 http(s)://，且網頁無法偽造 Origin，
    # 所以你瀏覽的其他網站沒辦法連 localhost 叫你開網址。
    origin = ws.request.headers.get("Origin", "")
    if not origin.startswith("chrome-extension://"):
        await ws.close(1008, "forbidden")
        return
    _bridges.add(ws)
    log(f"🔌 擴充功能已連線（{len(_bridges)}）→ 開分頁走擴充功能")
    try:
        async for payload in ws:
            if payload == "keepalive":
                continue
            try:
                request = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if not isinstance(request, dict):
                continue
            if request.get("type") == "progress":
                stages = {
                    "page_start": "頁面開始", "tickets_ready": "票數已選",
                    "ocr_start": "開始辨識", "captcha_filled": "驗證碼已填",
                    "manual_input": "保留手動輸入", "ocr_failed": "辨識失敗／分歧",
                    "submit_click": "已按確認張數",
                }
                stage = stages.get(request.get("stage"))
                page_ms = request.get("page_ms")
                if stage and isinstance(page_ms, (int, float)) and 0 <= page_ms < 86_400_000:
                    details = f"頁面起算 {page_ms:.0f}ms"
                    for key, label in (("total_ms", "收到通知後"), ("tab_ms", "開頁指令後")):
                        value = request.get(key)
                        if isinstance(value, (int, float)) and 0 <= value < 86_400_000:
                            details += f" | {label} {value:.0f}ms"
                    log(f"[流程] {stage} | {details} | {str(request.get('url', ''))[:300]}")
                continue
            if request.get("type") != "ocr":
                continue
            request_id = request.get("id")
            if not isinstance(request_id, str) or len(request_id) > 100:
                continue
            response = {"type": "ocr_result", "id": request_id, "strategy": "dual-normalized-v1"}
            try:
                response["text"] = await asyncio.to_thread(ocr.recognize, request.get("image"))
            except Exception as error:
                response["error"] = str(error)[:200]
            await ws.send(json.dumps(response))
    except Exception:
        pass
    finally:
        _bridges.discard(ws)
        if not _bridges:
            log("⚠ 擴充功能斷線 → 暫時改用 Popen 開分頁（會自動重連）")


def beep() -> None:
    try:
        import winsound

        winsound.Beep(1500, 300)
    except Exception:
        print("\a", end="", flush=True)


client = TelegramClient(str(BASE / "tg-monit"), int(CFG["api_id"]), CFG["api_hash"])


@client.on(events.NewMessage(chats=CFG["channels"]))
async def on_message(event):
    t_recv = time.time()
    t0 = time.perf_counter()
    links = extract_links(event.message)
    if not links:
        return

    now = time.monotonic()
    opened = []
    for url in links:
        if now - _last_opened.get(url, -1e9) < DEDUP:
            continue
        _last_opened[url] = now
        path = await open_url(url, t_recv)
        opened.append((url, path, (time.perf_counter() - t0) * 1000))

    if not opened:
        return
    if CFG.get("beep", True):
        threading.Thread(target=beep, daemon=True).start()

    # Telegram 的 message.date 只到整秒（小數捨去），所以這只是上限：實際網路延遲落在 (N-1000, N]
    tg_ms = (t_recv - event.message.date.timestamp()) * 1000
    chat = getattr(event.chat, "title", None) or event.chat_id
    first_line = next(
        (l for l in (event.raw_text or "").splitlines() if "剩餘" in l), ""
    ).strip()
    for url, path, local_ms in opened:
        log(
            f"{chat} | {first_line} | TG≤{tg_ms:.0f}ms | 本機{local_ms:.1f}ms({path}) | 開啟 {url}",
            timestamp=t_recv,
        )


async def main():
    async def warmup_ocr():
        try:
            await asyncio.to_thread(ocr.warmup)
            log("驗證碼雙模型辨識已就緒（原圖＋藍底白字處理；至少三次一致，且兩模型處理後結果相同才填入）")
        except Exception as error:
            log(f"⚠ 驗證碼辨識無法啟動，仍可手動輸入：{error}")

    ocr_task = asyncio.create_task(warmup_ocr())
    try:
        global _server
        _server = await serve(bridge_handler, "127.0.0.1", BRIDGE_PORT, max_size=1_500_000)
        log(f"擴充功能橋接：ws://127.0.0.1:{BRIDGE_PORT}（等待連線，連上前用 Popen）")
    except OSError as e:
        log(f"⚠ 橋接埠 {BRIDGE_PORT} 無法使用（{e}），全程改用 Popen 開分頁")

    await client.start()
    names = []
    for c in CFG["channels"]:
        try:
            ent = await client.get_entity(c)
            names.append(getattr(ent, "title", c))
        except Exception as e:
            log(f"⚠ 找不到頻道 {c}: {e}")
    log("監聽中：", "、".join(names))
    log(f"Popen 退路：{CHROME} --profile-directory={PROFILE}")
    log("購票頁需先載入 chrome-extension 擴充功能；可設定辨識填入後自動確認張數。")
    await client.run_until_disconnected()
    await ocr_task


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
