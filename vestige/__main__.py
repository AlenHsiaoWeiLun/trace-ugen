"""VESTIGE command line.

    python -m vestige                                     # build on first run, then serve the app on :8100
    python -m vestige build                               # run perception on the demo footage (~2 min)
    python -m vestige ask "What happened to my bicycle?"  # cited answer from World Memory
    python -m vestige alerts                              # open alerts across all sites
    python -m vestige lab                                 # latest IncidentLab results
    python -m vestige serve                               # HTTP API on :8100 (docs/vestige_api.md)
"""
import argparse
import json
import re
import sys

from . import db

SITES = ["construction", "road", "campus", "metro"]


def ensure_memory(rebuild=False):
    if rebuild or not db.DB_PATH.exists():
        from . import scenarios
        print("Building World Memory from the demo footage (~2 min)…", file=sys.stderr)
        try:
            scenarios.build(log=lambda *a: print(*a, file=sys.stderr))
        except (FileNotFoundError, RuntimeError) as exc:
            sys.exit(str(exc))


def show_answer(a: dict):
    cites = {c["n"]: c for c in a["citations"]}
    print(f"\n[{a['workspace']['name']}]  {a['question']}\n")
    print(re.sub(r"\[E(\d+)\]", r"[E\1]", a.get("headline") or " ".join(a["sentences"])), "\n")
    for s in a.get("steps", []):  # already in story order
        state = {"OBSERVED": "seen", "LAST_SEEN": "seen", "INFERRED": "inferred", "RECORDED": "recorded",
                 "UNKNOWN": "unknown", "REJECTED": "not linked"}.get(s["status"], s["status"].lower())
        ref = f"  [E{s['n']}]" if s.get("n") else ""
        print(f"  {(s['ts'] or '')[11:19]:8}  {state:10}  {s['title']}{' · ' + s['place'] if s.get('place') else ''}{ref}")
    if cites:
        print("\nEvidence")
        for n, c in cites.items():
            print(f"  E{n}  {c['status'].lower():9} {c['ts'][11:19]}  {(c.get('source') or '').split(' · ')[0]:7}  {(c.get('url') or '').lstrip('/')}")


def main():
    ap = argparse.ArgumentParser(prog="python -m vestige", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8100, help="port for the app (default command)")
    ap.add_argument("--rebuild", action="store_true", help="rebuild demo memory before serving")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="run perception on the demo footage and rebuild World Memory")
    q = sub.add_parser("ask", help="ask a question; the right site is chosen automatically")
    q.add_argument("question")
    q.add_argument("--json", action="store_true", help="print the full answer object")
    sub.add_parser("alerts", help="open alerts across all sites")
    sub.add_parser("lab", help="latest IncidentLab results")
    s = sub.add_parser("serve", help="start the HTTP API")
    s.add_argument("--port", type=int, default=8100)
    a = ap.parse_args()

    if a.cmd == "build":
        ensure_memory(rebuild=True)
        print("World Memory ready:", db.DB_PATH)
    elif a.cmd == "ask":
        ensure_memory()
        from . import agent
        c = db.connect()
        ws, _ = agent.route(c, a.question, SITES)
        ans = agent.ask(c, ws, a.question)
        print(json.dumps(ans, indent=2, ensure_ascii=False) if a.json else "", end="")
        if not a.json:
            show_answer(ans)
    elif a.cmd == "alerts":
        ensure_memory()
        from . import memory
        c = db.connect()
        for w in SITES:
            for e in memory.search_events(c, w):
                if e["status"] == "open":
                    d = (e.get("metrics") or {}).get("duration_s")
                    print(f"{w:13} {e['ts_start'][11:19]}  {e['priority']:6}  {e['title']}{f' · {d:.0f} s' if isinstance(d, (int, float)) else ''}")
    elif a.cmd == "lab":
        ensure_memory()
        c = db.connect()
        x = db.row(c.execute("SELECT * FROM experiments WHERE status='done' AND workspace_id='bench-road' "
                             "ORDER BY created_ts DESC").fetchone())
        if not x:
            sys.exit("No IncidentLab results yet.")
        cells = x["summary"]["cells"]
        print(f"IncidentLab {x['id']} · {x['workspace_id']} · detection retention vs clean frames (not accuracy)\n")
        for p in sorted({(c["perturbation"], c["level"], c["label"]) for c in cells}):
            base = next(c for c in cells if (c["perturbation"], c["level"]) == p[:2] and c["mitigation"] == "none")
            best = max((c for c in cells if (c["perturbation"], c["level"]) == p[:2] and c["mitigation"] != "none"),
                       key=lambda c: c["delta"], default=None)
            tail = f"→ {best['retention']:.0%} with {best['mitigation_label']} ({best['delta'] * 100:+.0f} pp)" if best else ""
            print(f"  {p[2]:18} L{p[1]}  {base['retention']:.0%}  {tail}")
    else:  # no command, or "serve"
        ensure_memory(rebuild=a.rebuild)
        import uvicorn
        port = getattr(a, "port", 8100)
        print(f"VESTIGE → http://127.0.0.1:{port}", file=sys.stderr)
        uvicorn.run("vestige.api:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
