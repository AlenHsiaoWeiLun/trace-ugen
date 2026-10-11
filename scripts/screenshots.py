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
from scripts.record_demo import CDP, CHROME  # noqa: E402

BASE = "http://127.0.0.1:8100/"
SHOTS = [
    # name, hash, width, height, js-after-load, wait
    ("01_ask_answer", "#/ask?ws=campus&q=What%20happened%20to%20my%20bicycle%3F", 1600, 1000, None, 4),
    ("02_memory", "#/memory?ws=campus", 1600, 1000, None, 3),
    ("03_investigate_metro", "#/investigate?ws=metro", 1600, 1000, None, 4),
    ("04_investigate_construction", "#/investigate?ws=construction", 1600, 1000,
     "document.querySelectorAll('.sug')[1]?.click()", 5),
    ("05_incidentlab", "#/lab?ws=campus", 1600, 1000,
     "[...document.querySelectorAll('*')].find(e=>e.textContent.trim().startsWith('X-dae2cec5') && e.children.length<3)?.click()", 4),
    ("05b_incidentlab_results", "#/lab?ws=campus", 1600, 1000,
     "[...document.querySelectorAll('*')].find(e=>e.textContent.trim().startsWith('X-dae2cec5') && e.children.length<3)?.click();"
     "setTimeout(()=>document.querySelector('.stats')?.scrollIntoView({block:'start'}),2000)", 5),
    ("06_sources", "#/sources?ws=campus", 1600, 1000, None, 3),
    ("07_settings", "#/settings?ws=campus", 1600, 1000, None, 3),
    ("08_mobile_ask", "#/ask?ws=campus&q=What%20happened%20to%20my%20bicycle%3F", 390, 844, None, 4),
    ("09_mobile_investigate", "#/investigate?ws=construction", 390, 844, None, 4),
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
            for name, h, w, hh, js, wait in SHOTS:
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
