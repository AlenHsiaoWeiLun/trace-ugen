"""Render the Slides-artifact files locally: PDF + per-slide PNG previews (headless Chrome)."""
import json, re, subprocess, sys
from pathlib import Path

D = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
deck = json.loads((D / "artifact/project/deck.json").read_text())
blobs = json.loads((D / "blobs.json").read_text())
only = sys.argv[1:]  # optional slide ids
order = [s for s in deck["order"] if not only or s in only]
links = "".join(f'<link rel="stylesheet" href="{f["href"]}">' for f in deck["faces"].values())
secs = []
for sid in order:
    p = D / f"artifact/project/slides/{sid}.html"
    if not p.exists():
        continue
    h = p.read_text()
    h = re.sub(r"/_blob/([0-9a-f]{32})", lambda m: (D / blobs.get(m.group(1), "missing.png")).as_uri(), h)
    h = re.sub(r"<aside>.*?</aside>", "", h, flags=re.S)
    secs.append(h)
css = ("@page{size:1920px 1080px;margin:0}*{box-sizing:border-box;margin:0;padding:0}"
       "body{background:#000}section{width:1920px;height:1080px;position:relative;overflow:hidden;"
       "page-break-after:always;break-after:page}section>*{flex-shrink:0}h1,h2,h3{font-weight:600}"
       "ul,ol{padding-left:1.2em}table{border-collapse:collapse}"
       "td,th{padding:0.45em 0.6em;border-bottom:1px solid rgba(140,135,126,0.45);vertical-align:top}th{font-weight:600}")
html = f"<!doctype html><html><head><meta charset=utf-8>{links}<style>{css}</style></head><body>{''.join(secs)}</body></html>"
out = D / "build"
out.mkdir(exist_ok=True)
(out / "deck.html").write_text(html)
pdf = out / ("subset.pdf" if only else "VESTIGE_deck.pdf")
subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=10000",
                "--allow-file-access-from-files", f"--print-to-pdf={pdf}", (out / "deck.html").as_uri()],
               check=True, capture_output=True)
import pymupdf
doc = pymupdf.open(pdf)
prev = out / "preview"
prev.mkdir(exist_ok=True)
for i, (sid, pg) in enumerate(zip(order, doc)):
    pg.get_pixmap(dpi=36).save(prev / f"{sid}.png")
print(pdf, len(doc), "pages")
