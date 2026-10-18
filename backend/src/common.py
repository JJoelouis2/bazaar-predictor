import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND / "config"
DATASTORE = BACKEND / "datastore"
HISTORY_DIR = DATASTORE / "history"
ELECTIONS_PATH = DATASTORE / "elections.jsonl"
MODELS_DIR = BACKEND / "models"
FRONTEND_DATA = BACKEND.parent / "frontend" / "data"
TEMP_DATA = BACKEND.parent / "data"

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND.parent / ".env")
    load_dotenv(BACKEND / ".env")
except ImportError:
    pass

HYPIXEL_BAZAAR_URL = "https://api.hypixel.net/skyblock/bazaar"
HYPIXEL_ELECTION_URL = "https://api.hypixel.net/v2/resources/skyblock/election"
COFLNET_HISTORY_URL = "https://sky.coflnet.com/api/bazaar/{tag}/history"

GRID_SECONDS = 2 * 3600
MINISTER_WEIGHT = 0.35


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def load_watchlist():
    return load_json(CONFIG_DIR / "watchlist.json")


def load_calendar():
    path = CONFIG_DIR / "event_calendar.json"
    if not path.exists():
        return {"minister_weight": MINISTER_WEIGHT, "terms": [], "updates": []}
    cal = load_json(path)
    cal.setdefault("minister_weight", MINISTER_WEIGHT)
    cal.setdefault("terms", [])
    cal.setdefault("updates", [])
    return cal


def watchlist_ids():
    return [item["id"] for item in load_watchlist()["items"]]


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def parse_iso(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def align_grid(dt, seconds=GRID_SECONDS):
    epoch = int(dt.replace(tzinfo=timezone.utc).timestamp())
    aligned = epoch - (epoch % seconds)
    return datetime.utcfromtimestamp(aligned)


def http_get_json(url, params=None, headers=None, timeout=30, retries=5, backoff=2.0):
    merged = {"User-Agent": "bazaar-predictor/1.0"}
    if headers:
        merged.update(headers)
    api_key = os.environ.get("HYPIXEL_API_KEY", "").strip()
    if api_key and "api.hypixel.net" in url:
        merged["API-Key"] = api_key
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=merged, timeout=timeout)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", backoff * (attempt + 1)))
                time.sleep(min(wait, 60))
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as err:
            last_err = err
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_err}")


def append_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def dedupe_by_t(rows):
    seen = {}
    for row in rows:
        seen[row["t"]] = row
    return [seen[k] for k in sorted(seen)]


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def history_path(item_id):
    safe = item_id.replace(":", "_")
    return HISTORY_DIR / f"{safe}.jsonl"


def load_item_rows(item_id):
    return dedupe_by_t(read_jsonl(history_path(item_id)))


def normalize_prices(row):
    instabuy = float(row.get("instabuy") or 0)
    instasell = float(row.get("instasell") or 0)
    if 0 < instabuy < instasell:
        row["instabuy"], row["instasell"] = instasell, instabuy
    return row
