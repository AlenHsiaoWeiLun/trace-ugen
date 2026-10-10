"""Fill measured numbers into deck/deck.html, export PDF with headless Chrome, render previews.

    python scripts/build_deck.py --github https://github.com/... --video https://youtu.be/...
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "deck"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", default="github.com/AlenHsiaoWeiLun/trace-ugen")
    ap.add_argument("--video", default="youtu.be/ — link added after upload")
    ap.add_argument("--out", default=str(ROOT / "deck" / "b13902049_CN_league.pdf"))
    a = ap.parse_args()

    metro = json.loads((ROOT / "data/run_metro.json").read_text())
    road = json.loads((ROOT / "data/run_road.json").read_text())
    st = metro["pipeline"]["stage_ms"]
    shots = DECK / "shots"
    shots.mkdir(exist_ok=True)
    inc = {i["id"]: i for i in metro["incidents"] + road["incidents"]}
    high = next(i for i in metro["incidents"] if i["priority"] == "high")
    train = next((i for i in metro["incidents"] if i.get("vlm") and i["vlm"].get("second_opinion")), None)
    shutil.copy(ROOT / high["keyframe"].lstrip("/"), shots / "metro_incident.jpg")
    if train:
        shutil.copy(ROOT / train["keyframe"].lstrip("/"), shots / "train.jpg")
    if road["incidents"]:
        shutil.copy(ROOT / road["incidents"][0]["keyframe"].lstrip("/"), shots / "road.jpg")

    html = (DECK / "deck.html").read_text()
    vlm_ms = [i["vlm"]["ms"] for i in inc.values() if i.get("vlm")]
    rep = {
        "MS_DETECT": f'{st["detect"]:.0f}',
        "MS_TRACK": f'{st.get("track", 0) + st.get("rules", 0):.1f}',
        "MS_FUSION": f'{st["fusion"]:.2f}',
        "MS_ASR": f'{st.get("asr", 0):,.0f}',
        "MS_VLM": f'{sum(vlm_ms) / len(vlm_ms):,.0f}' if vlm_ms else "n/a",
        "DEVICE_NAME": metro["pipeline"]["device"],
        "VLM_ANSWER": train["vlm"]["second_opinion"]["answer"] if train else "n/a",
        "GITHUB_URL": a.github,
        "VIDEO_URL": a.video,
    }
    for k, v in rep.items():
        html = html.replace(k, v)
    if train:
        surge = next(s for s in train["signals"] if s["kind"] == "crowd_surge")
        html = html.replace("people 7 → 11 within 6 s", surge["detail"].replace("people count ", "people "))
    built = DECK / "_build.html"
    built.write_text(html)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                    f"--print-to-pdf={a.out}", built.as_uri()], check=True, capture_output=True)
    print("wrote", a.out)
    prev = DECK / "preview"
    prev.mkdir(exist_ok=True)
    import pymupdf

    d = pymupdf.open(a.out)
    print(len(d), "pages")
    for i, p in enumerate(d):
        p.get_pixmap(dpi=36).save(prev / f"p{i + 1:02d}.png")


if __name__ == "__main__":
    main()
