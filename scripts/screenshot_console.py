"""Clean 1920x1080 console screenshot for the deck (server must run with --demo)."""
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import urllib.request

import websockets

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from scripts.record_demo import CDP, CHROME, URL, post  # noqa: E402


async def main(out: str):
    post("/api/demo/reset")
    for i in ("INC-R-0001", "INC-M-0002", "INC-M-0001"):
        post(f"/api/demo/release/{i}")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9334",
                               f"--user-data-dir={tempfile.mkdtemp()}", "--window-size=1920,1080", "--hide-scrollbars",
                               "--disable-gpu", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9334/json").read())
                break
            except OSError:
                await asyncio.sleep(0.2)
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**26) as ws:
            c = CDP(ws)
            pump = asyncio.create_task(c.pump())
            await c.call("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
            await c.call("Page.enable")
            await c.call("Page.navigate", url=URL)
            await asyncio.sleep(4)
            await c.js("selectIncident('INC-M-0001')")
            await asyncio.sleep(1.5)
            await c.js("(() => {const e=document.getElementById('askInput'); e.value='Anything near exit C?';"
                       " e.dispatchEvent(new Event('input',{bubbles:true})); document.getElementById('askForm').requestSubmit();})()")
            await asyncio.sleep(9)
            shot = await c.call("Page.captureScreenshot", format="png")
            open(out, "wb").write(base64.b64decode(shot["data"]))
            pump.cancel()
    finally:
        chrome.terminate()
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
