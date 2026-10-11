"""Full-resolution screenshots of every VESTIGE page (server must run on :8100).

    python scripts/screenshots.py out_dir
"""
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.browser_capture import CDP, CHROME  # noqa: E402

BASE = "http://127.0.0.1:8100/"
SHOTS = [
    # name, hash, width, height, js-after-load, wait
    ("00_home", "#/ask?ws=construction", 1600, 1000, None, 6),
    ("00b_home_alerts", "#/ask?ws=construction", 1600, 1000, "window.scrollTo(0, 700)", 3),
    ("01_answer_construction_alerts", "#/ask?ws=construction&q=What%20safety%20alerts%20happened%20today%3F", 1600, 1000, None, 5),
    ("02_answer_alert_why", "#/ask?ws=construction&event=EV-CAM-S1-prox-1-3", 1600, 1000, None, 5),
    ("03_answer_bicycle", "#/ask?ws=campus&q=What%20happened%20to%20my%20bicycle%3F", 1600, 1000, None, 5),
    ("04_answer_bicycle_map", "#/ask?ws=campus&q=What%20happened%20to%20my%20bicycle%3F", 1600, 1000,
     "setTimeout(()=>document.querySelector('.omap')?.scrollIntoView({block:'center'}),2500)", 5),
    ("05_answer_metro", "#/ask?ws=metro&q=What%20happened%20before%20the%20emergency%20alert%3F", 1600, 1000, None, 5),
    ("06_detection_lab", "#/lab?ws=construction", 1600, 1000, None, 4),
    ("07_sources", "#/sources?ws=construction", 1600, 1000, None, 3),
    ("08a_mobile_home", "#/ask?ws=construction", 390, 844, None, 6),
    ("08_mobile_answer", "#/ask?ws=construction&q=What%20safety%20alerts%20happened%20today%3F", 390, 844, None, 5),
    ("09_mobile_bicycle", "#/ask?ws=campus&q=What%20happened%20to%20my%20bicycle%3F", 390, 844, None, 5),
]


async def shoot(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9335", f"--user-data-dir={tempfile.mkdtemp()}",
                               "--hide-scrollbars", "--disable-gpu", "about:blank"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9335/json").read())
                break
            except OSError:
                await asyncio.sleep(0.2)
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**27) as ws:
            c = CDP(ws)
            pump = asyncio.create_task(c.pump())
            await c.call("Page.enable")
            only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
            for name, h, w, hh, js, wait in SHOTS:
                if only and not any(name.startswith(o) for o in only):
                    continue
                await c.call("Emulation.setDeviceMetricsOverride", width=w, height=hh, deviceScaleFactor=2 if w < 800 else 1,
                             mobile=w < 800)
                await c.call("Page.navigate", url=BASE + "?" + name + h)
                await asyncio.sleep(2.5)
                if js:
                    await c.js(js)
                await asyncio.sleep(wait)
                shot = await c.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
                (out / f"{name}.png").write_bytes(base64.b64decode(shot["data"]))
                print("shot", name)
            pump.cancel()
    finally:
        chrome.terminate()


if __name__ == "__main__":
    asyncio.run(shoot(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")))
