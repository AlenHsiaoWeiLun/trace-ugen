"""Record the console demo with headless Chrome (CDP screencast), timed to the narration.

Requires the server in demo mode:  python -m traceai.server --demo --port 8000
    python scripts/record_demo.py video/build/narration_timed.json video/build/demo.mp4
"""
from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://127.0.0.1:8000/"
GAP = 0.5  # silence between narration segments, must match assemble_video.py


class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.pending, self.frames = ws, 0, {}, []

    async def call(self, method, **params):
        self.n += 1
        fut = asyncio.get_event_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        return await fut

    async def pump(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg.get("result"))
            elif msg.get("method") == "Page.screencastFrame":
                p = msg["params"]
                self.frames.append((time.monotonic(), base64.b64decode(p["data"])))
                await self.ws.send(json.dumps({"id": 0, "method": "Page.screencastFrameAck",
                                               "params": {"sessionId": p["sessionId"]}}))

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True)
        return (r or {}).get("result", {}).get("value")

    async def key(self, k):
        for t in ("keyDown", "keyUp"):
            await self.call("Input.dispatchKeyEvent", type=t, key=k, text=k if t == "keyDown" else None)

    async def type(self, text, delay=0.06):
        for ch in text:
            await self.call("Input.insertText", text=ch)
            await asyncio.sleep(delay)


def post(path):
    urllib.request.urlopen(urllib.request.Request(URL.rstrip("/") + path, method="POST"), timeout=10).read()


SCROLL = "document.querySelector('.detail-panel').scrollTo({top: %s, behavior: 'smooth'})"
SCROLL_TO = ("(() => {const p=document.querySelector('.detail-panel'), e=document.querySelector('%s');"
             " if(p&&e) p.scrollTo({top: e.offsetTop - p.offsetTop - 16, behavior:'smooth'});})()")
# Smooth camera move: scale the whole page around a point (fractions of the viewport).
ZOOM = ("(() => {const r=document.documentElement; r.style.transition='transform .8s cubic-bezier(.2,.7,.2,1)';"
        " r.style.transformOrigin='%s%% %s%%'; r.style.transform='scale(%s)';})()")
UNZOOM = ZOOM % (50, 50, 1)
HOVER = ("(() => {const e=document.querySelector('%s'); if(!e) return;"
         " e.dispatchEvent(new MouseEvent('mouseover',{bubbles:true})); e.classList.add('highlighted');})()")


async def choreography(c: CDP, seg: str, dur: float):
    """Actions per narration segment; each must take <= dur seconds of wall time."""
    t0 = time.monotonic()

    async def at(t):
        await asyncio.sleep(max(0, t - (time.monotonic() - t0)))

    if seg == "d01":
        post("/api/demo/release/INC-R-0001")
        await at(1.0)
        await c.js("selectIncident('INC-R-0001')")
    elif seg == "d02":
        post("/api/demo/release/INC-M-0001")
        await at(2.2)
        await c.js("selectIncident('INC-M-0001')")
        await at(6.0)
        await c.js(SCROLL_TO % ".signal")
        await c.js(ZOOM % (45, 70, 1.45))
        await at(7.0)
        await c.js(HOVER % ".signal[data-source='detector']")
        await at(9.5)
        await c.js(HOVER % ".signal[data-source='radio']")
        await c.js(SCROLL_TO % ".signal[data-source='radio']")
    elif seg == "d03":
        await c.js(UNZOOM)
        await c.js(SCROLL % 0)
        await at(4.0)
        await c.js(SCROLL_TO % ".summary-block")
        await c.js(ZOOM % (45, 60, 1.4))
        await at(6.0)
        await c.js(HOVER % ".summary-block .citation-chip")
    elif seg == "d04":
        await c.js(SCROLL % 0)
        await c.js(ZOOM % (45, 18, 1.5))
        await at(0.6)
        # Re-query the input for every character: the console re-renders while polling.
        for ch in "Anything near exit C?":
            await c.js("(() => {const e=document.getElementById('askInput'); if(!e) return; e.focus();"
                       f" e.value += {json.dumps(ch)}; e.dispatchEvent(new Event('input', {{bubbles:true}}));}})()")
            await asyncio.sleep(0.05)
        await c.js("document.getElementById('askForm').requestSubmit()")
    elif seg == "d05":
        await c.js(UNZOOM)
        await at(0.5)
        post("/api/demo/release/INC-M-0002")
        await at(2.5)
        await c.js("selectIncident('INC-M-0002')")
        await at(7.0)
        await c.js(SCROLL_TO % ".vlm-block")
        await c.js(ZOOM % (45, 55, 1.45))
        await at(12.0)
        await c.js("(() => {const a=document.querySelector('.audit-list, #auditLog, .audit');"
                   " if(a) a.scrollIntoView({behavior:'smooth', block:'center'});})()")
    elif seg == "d06":
        await c.js(UNZOOM)
        await c.js("document.querySelector(\".tab[data-scenario='road']\")?.click()")
        await at(0.8)
        await c.js("selectIncident('INC-R-0001')")
        await at(6.5)
        await c.js(SCROLL_TO % ".summary-block")
    elif seg == "d07":
        await c.js(UNZOOM)
        await c.js("document.querySelector(\".tab[data-scenario='all']\")?.click()")
        await at(0.6)
        await c.js("selectIncident('INC-M-0001')")
        await at(2.2)
        await c.key("c")
        await c.js("document.querySelector(\"[data-review='confirmed']\")?.click()")
    await at(dur)


async def main(timed_json: str, out: str):
    segs = [s for s in json.loads(Path(timed_json).read_text()) if s["id"].startswith("d")]
    post("/api/demo/reset")
    prof = tempfile.mkdtemp()
    chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={prof}",
                               "--window-size=1920,1080", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required",
                               "--force-device-scale-factor=1", "--disable-gpu", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json").read())
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
            await asyncio.sleep(4.0)  # fonts, icons, first poll
            await c.call("Page.startScreencast", format="jpeg", quality=88, maxWidth=1920, maxHeight=1080)
            start = time.monotonic()
            marks = []
            for s in segs:
                marks.append((s["id"], round(time.monotonic() - start, 2)))
                await choreography(c, s["id"], s["dur"] + GAP)
            end = time.monotonic()
            await c.call("Page.stopScreencast")
            pump.cancel()
    finally:
        chrome.terminate()

    # Frames arrive only on change: write each with its display duration, then resample to 30 fps.
    tmp = Path(tempfile.mkdtemp())
    frames = [f for f in c.frames if f[0] >= start] or c.frames[-1:]
    lines = []
    for i, (t, data) in enumerate(frames):
        (tmp / f"{i:05d}.jpg").write_bytes(data)
        nxt = frames[i + 1][0] if i + 1 < len(frames) else end
        lines += [f"file '{tmp / f'{i:05d}.jpg'}'", f"duration {max(nxt - max(t, start), 0.001):.4f}"]
    lines.append(f"file '{tmp / f'{len(frames) - 1:05d}.jpg'}'")
    (tmp / "list.txt").write_text("\n".join(lines))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                    "-vf", "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out], check=True)
    print(f"{len(frames)} frames, {end - start:.1f}s -> {out}; marks {marks}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
