"""README demo GIF: a short walk through the app (server must run on :8100).

    python scripts/demo_gif.py docs/demo.gif
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
# (hash, js after load, [(wait seconds, hold seconds in the GIF), ...])
STEPS = [
    ("#/ask?ws=construction", None, [(4, 1.6), (3.2, 1.6), (3.2, 1.6)]),        # showcase auto-advances
    ("#/ask?ws=construction&q=What%20safety%20alerts%20happened%20today%3F", None, [(4, 2.8)]),
    ("#/ask?ws=construction&event=EV-CAM-S1-prox-1-3", None, [(4, 3.0)]),
    ("#/ask?ws=campus&q=What%20happened%20to%20my%20bicycle%3F", None, [(4, 3.0)]),
    ("#/ask?ws=campus&q=What%20happened%20to%20my%20bicycle%3F",
     "document.querySelector('.omap')?.scrollIntoView({block:'center'})", [(4, 2.6)]),
    ("#/ask?ws=metro&q=What%20happened%20before%20the%20emergency%20alert%3F", None, [(4, 2.8)]),
]


async def main(out: Path):
    tmp = Path(tempfile.mkdtemp())
    chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9336", f"--user-data-dir={tempfile.mkdtemp()}",
                               "--hide-scrollbars", "--disable-gpu", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames = []
    try:
        for _ in range(50):
            try:
                targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9336/json").read())
                break
            except OSError:
                await asyncio.sleep(0.2)
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**27) as ws:
            c = CDP(ws)
            pump = asyncio.create_task(c.pump())
            await c.call("Page.enable")
            await c.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
            for k, (h, js, shots) in enumerate(STEPS):
                await c.call("Page.navigate", url=f"{BASE}?g{k}{h}")
                for wait, hold in shots:
                    await asyncio.sleep(wait)
                    if js:
                        await c.js(js)
                    shot = await c.call("Page.captureScreenshot", format="png")
                    f = tmp / f"{len(frames):02d}.png"
                    f.write_bytes(base64.b64decode(shot["data"]))
                    frames.append((f, hold))
            pump.cancel()
    finally:
        chrome.terminate()
    concat = tmp / "list.txt"
    concat.write_text("".join(f"file '{f}'\nduration {d}\n" for f, d in frames) + f"file '{frames[-1][0]}'\n")
    vf = "scale=1080:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-vf", vf, str(out)], check=True)
    print(out, f"{out.stat().st_size / 1e6:.1f} MB", len(frames), "frames")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/demo.gif")))
