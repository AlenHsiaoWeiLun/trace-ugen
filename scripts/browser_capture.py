"""Shared Chrome DevTools client for the VESTIGE screenshot and GIF utilities."""
from __future__ import annotations

import asyncio
import base64
import json
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


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

