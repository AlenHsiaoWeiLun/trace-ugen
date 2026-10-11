"""`python -m vestige` — build the demo memory from footage on first run, then serve the app.

    python -m vestige            # http://127.0.0.1:8100
    python -m vestige --rebuild  # re-run perception on all demo footage
"""
import argparse
import sys

import uvicorn

from . import db

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8100)
ap.add_argument("--rebuild", action="store_true")
a = ap.parse_args()

if a.rebuild or not db.DB_PATH.exists():
    from . import scenarios
    print("Building World Memory from demo footage (first run, ~2 min)…")
    try:
        scenarios.build()
    except (FileNotFoundError, RuntimeError) as exc:
        sys.exit(str(exc))

print(f"VESTIGE → http://127.0.0.1:{a.port}")
uvicorn.run("vestige.api:app", host="127.0.0.1", port=a.port, log_level="warning")
