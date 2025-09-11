
import json, time, os, threading
from pathlib import Path

_LOCK = threading.RLock()
LOG_PATH = os.environ.get("EVENT_LOG_PATH", "/app/logs/events.log")
STATUS_PATH = os.environ.get("STATUS_SNAPSHOT_PATH", "/app/logs/status.json")

def _ensure_dir():
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)

def event_log(kind: str, **data):
    rec = {"ts": int(time.time()),
           "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "event": kind, **data}
    line = json.dumps(rec, ensure_ascii=False)
    _ensure_dir()
    with _LOCK, open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n"); f.flush(); os.fsync(f.fileno())

def write_status(status: dict):
    _ensure_dir()
    snap = dict(status); snap["ts"] = int(time.time())
    with _LOCK, open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
