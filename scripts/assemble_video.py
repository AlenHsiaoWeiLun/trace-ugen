"""Assemble the ≤3-min demo video: deck pages + recorded console demo + narration + captions.

    python scripts/assemble_video.py video/build/narration_timed.json deck/b13902049_CN_league.pdf \
        video/build/demo.mp4 video/TRACE_demo.mp4
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GAP = 0.5
FPS = 30
W, H = 1920, 1080
BUILD = Path("video/build")


def sh(*args):
    subprocess.run([str(a) for a in args], check=True)


def font(size):
    for f in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def slide_clip(page_png: Path, dur: float, out: Path):
    n = int(round(dur * FPS))
    sh("ffmpeg", "-y", "-v", "error", "-i", page_png, "-vf",
       f"scale=2112:1188,zoompan=z='min(1+0.00025*on,1.045)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
       f":d={n}:s={W}x{H}:fps={FPS},fade=t=in:st=0:d=0.25,fade=t=out:st={max(dur - 0.25, 0):.2f}:d=0.25",
       "-frames:v", n, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out)


def caption_png(text: str, out: Path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(38)
    lines = textwrap.wrap(text, 62)
    lh = 50
    box_h = lh * len(lines) + 28
    y0 = H - 70 - box_h
    widths = [d.textlength(l, font=f) for l in lines]
    bw = max(widths) + 56
    d.rounded_rectangle([(W - bw) / 2, y0, (W + bw) / 2, y0 + box_h], 12, fill=(8, 11, 16, 200))
    for i, l in enumerate(lines):
        d.text(((W - widths[i]) / 2, y0 + 14 + i * lh), l, font=f, fill=(236, 240, 245, 255))
    img.save(out)


def chunks(text: str, max_words: int = 13):
    words = text.split()
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 6 and w[-1] in ".,?!:"):
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def main(timed: str, pdf: str, demo: str, out: str):
    import pymupdf

    segs = json.loads(Path(timed).read_text())
    BUILD.mkdir(parents=True, exist_ok=True)
    pages = BUILD / "pages"
    pages.mkdir(exist_ok=True)
    doc = pymupdf.open(pdf)
    for i, p in enumerate(doc):
        p.get_pixmap(dpi=72).save(pages / f"p{i + 1:02d}.png")

    # Video parts in order; consecutive demo segments are one cut from the recording.
    parts, t, demo_start, cap_events = [], 0.0, None, []
    demo_total = sum(s["dur"] + GAP for s in segs if s["visual"].startswith("demo"))
    for s in segs:
        dur = s["dur"] + GAP
        if s["visual"].startswith("slide:"):
            clip = BUILD / f"part_{s['id']}.mp4"
            slide_clip(pages / f"p{int(s['visual'].split(':')[1]):02d}.png", dur, clip)
            parts.append(clip)
        elif demo_start is None:
            demo_start = t
            clip = BUILD / "part_demo.mp4"
            sh("ffmpeg", "-y", "-v", "error", "-i", demo, "-t", f"{demo_total:.3f}", "-vf",
               "fade=t=in:st=0:d=0.3", "-r", FPS, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", clip)
            parts.append(clip)
        # caption timing: proportional to words within the spoken part of the segment
        cs = chunks(s["text"])
        nw = [len(c.split()) for c in cs]
        acc = t + 0.05
        for c, k in zip(cs, nw):
            d = s["dur"] * k / sum(nw)
            cap_events.append((acc, acc + d, c))
            acc += d
        t += dur

    lst = BUILD / "parts.txt"
    lst.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))
    silent = BUILD / "silent.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent)

    # narration: segments separated by GAP of silence
    alist = BUILD / "audio.txt"
    gap = BUILD / "gap.wav"
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", GAP, gap)
    wavs = []
    for s in segs:
        w = BUILD / "audio" / f"{s['id']}.wav"
        sh("ffmpeg", "-y", "-v", "error", "-i", BUILD / "audio" / f"{s['id']}.mp3", "-ar", 24000, "-ac", 1, w)
        wavs += [w, gap]
    alist.write_text("\n".join(f"file '{w.resolve()}'" for w in wavs))
    narration = BUILD / "narration.wav"
    sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", alist, narration)

    # captions as timed overlays
    capdir = BUILD / "captions"
    capdir.mkdir(exist_ok=True)
    inputs, filt, last = [], [], "0:v"
    for i, (a, b, text) in enumerate(cap_events):
        png = capdir / f"c{i:03d}.png"
        caption_png(text, png)
        inputs += ["-i", png]
        filt.append(f"[{last}][{i + 2}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[v{i}]")
        last = f"v{i}"
    sh("ffmpeg", "-y", "-v", "error", "-i", silent, "-i", narration, *inputs, "-filter_complex", ";".join(filt),
       "-map", f"[{last}]", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
       "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                               capture_output=True, text=True).stdout)
    print(f"wrote {out}: {dur:.1f}s, {len(cap_events)} captions")


if __name__ == "__main__":
    main(*sys.argv[1:5])
