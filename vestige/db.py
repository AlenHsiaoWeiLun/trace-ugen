"""World Memory store (SQLite).

Every row carries provenance so real observations, inferences, human annotations, staged demo
inputs and synthetic test data are never silently merged:

    observations.status   RECORDED | OBSERVED | LAST_SEEN | INFERRED | UNKNOWN
    *.provenance          public-footage | staged | user | synthetic | derived
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "vestige.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, description TEXT,
  retention_days INTEGER DEFAULT 30, created_ts TEXT);
CREATE TABLE IF NOT EXISTS zones (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT, kind TEXT,
  x REAL, y REAL, w REAL, h REAL);
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT, kind TEXT,
  zone_id TEXT, media_path TEXT, start_ts TEXT, fps REAL, duration_s REAL, width INTEGER, height INTEGER,
  status TEXT DEFAULT 'registered', recording_available INTEGER DEFAULT 1, provenance TEXT, license TEXT,
  map_x REAL, map_y REAL, notes TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS topology (
  workspace_id TEXT, a_source TEXT, b_source TEXT, min_travel_s REAL, max_travel_s REAL,
  PRIMARY KEY (workspace_id, a_source, b_source));
CREATE TABLE IF NOT EXISTS objects (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, label TEXT, cls TEXT, description TEXT, owner TEXT,
  appearance TEXT, provenance TEXT, created_ts TEXT);
CREATE TABLE IF NOT EXISTS tracks (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, source_id TEXT, cls TEXT, start_ts TEXT, end_ts TEXT,
  n_frames INTEGER, object_id TEXT, appearance TEXT, path TEXT, model TEXT);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, source_id TEXT, kind TEXT, path TEXT, ts TEXT,
  frame_idx INTEGER, t_offset_s REAL, bbox TEXT, sha256 TEXT, provenance TEXT, caption TEXT, created_ts TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, source_id TEXT, ts TEXT, kind TEXT, status TEXT,
  object_id TEXT, track_id TEXT, zone_id TEXT, bbox TEXT, frame_idx INTEGER, evidence_id TEXT,
  model TEXT, confidence REAL, provenance TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT, title TEXT, ts_start TEXT, ts_end TEXT,
  priority TEXT, status TEXT DEFAULT 'open', summary TEXT, provenance TEXT, model TEXT, metrics TEXT,
  evidence_id TEXT, zone_id TEXT);
CREATE TABLE IF NOT EXISTS event_links (
  event_id TEXT, observation_id TEXT, role TEXT, PRIMARY KEY (event_id, observation_id));
CREATE TABLE IF NOT EXISTS relations (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT, a_id TEXT, b_id TEXT, status TEXT,
  basis TEXT, created_ts TEXT);
CREATE TABLE IF NOT EXISTS gaps (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, source_id TEXT, ts_start TEXT, ts_end TEXT,
  reason TEXT, provenance TEXT);
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY, workspace_id TEXT, created_ts TEXT, model TEXT, scope TEXT, config TEXT,
  status TEXT, summary TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS experiment_results (
  id TEXT PRIMARY KEY, experiment_id TEXT, frame_ref TEXT, perturbation TEXT, params TEXT,
  mitigation TEXT, n_ref INTEGER, n_kept INTEGER, n_new INTEGER, latency_ms REAL, details TEXT,
  original_path TEXT, perturbed_path TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT, target TEXT, status TEXT, progress REAL, message TEXT,
  created_ts TEXT, updated_ts TEXT);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT, ts TEXT, actor TEXT, action TEXT, target TEXT,
  note TEXT);
CREATE INDEX IF NOT EXISTS obs_ws_ts ON observations(workspace_id, ts);
CREATE INDEX IF NOT EXISTS obs_obj ON observations(object_id);
CREATE INDEX IF NOT EXISTS ev_ws ON events(workspace_id, ts_start);
"""

JSON_COLS = {"appearance", "path", "bbox", "basis", "config", "summary", "params", "details", "metrics", "meta"}

_local = threading.local()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    key = str(p)
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    if key not in conns:
        p.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(key, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        try:  # databases built before document evidence existed
            c.execute("ALTER TABLE evidence ADD COLUMN meta TEXT")
        except sqlite3.OperationalError:
            pass
        conns[key] = c
    return conns[key]


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str) and d[k][:1] in "[{":
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass  # free text that merely starts with a bracket
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]


def insert(c: sqlite3.Connection, table: str, data: dict, replace: bool = True) -> None:
    vals = {k: (json.dumps(v) if k in JSON_COLS and not isinstance(v, str) and v is not None else v)
            for k, v in data.items()}
    cols = ",".join(vals)
    q = ",".join("?" for _ in vals)
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    c.execute(f"{verb} INTO {table} ({cols}) VALUES ({q})", list(vals.values()))


def audit(c: sqlite3.Connection, workspace_id: str | None, actor: str, action: str, target: str = "",
          note: str = "") -> None:
    c.execute("INSERT INTO audit (workspace_id, ts, actor, action, target, note) VALUES (?,?,?,?,?,?)",
              (workspace_id, now(), actor, action, target, note))


def reset(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    conns = getattr(_local, "conns", {})
    if str(p) in conns:
        conns.pop(str(p)).close()
    for suffix in ("", "-wal", "-shm"):
        Path(str(p) + suffix).unlink(missing_ok=True)
    return connect(p)
