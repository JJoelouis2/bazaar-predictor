from datetime import datetime, timezone

import numpy as np
import pandas as pd

DEFAULT_INTERVALS = [
    {"id": "pre", "label": "1d before", "start_off_days": -1, "end_off_days": 0},
    {"id": "day1", "label": "1d during", "start_off_days": 0, "end_off_days": 1},
    {"id": "post", "label": "1d after", "start_off_days": 1, "end_off_days": 2},
]


def window_return(df, start_ts, interval, min_points, max_stale_h):
    a = start_ts + pd.Timedelta(days=interval["start_off_days"])
    b = start_ts + pd.Timedelta(days=interval["end_off_days"])
    window = df.loc[(df.index >= a) & (df.index <= b)]
    if len(window) < min_points:
        return None
    if float(window["stale_h"].max()) >= max_stale_h:
        return None
    p0 = float(window["mid"].iloc[0])
    p1 = float(window["mid"].iloc[-1])
    if p0 <= 0 or p1 <= 0:
        return None
    return p1 / p0 - 1.0


def interval_stats(vals, cur_mid):
    arr = np.array(vals, dtype=float)
    med = float(np.median(arr))
    return {
        "n": int(len(arr)),
        "median": round(med, 5),
        "mean": round(float(arr.mean()), 5),
        "std": round(float(arr.std(ddof=0)), 5) if len(arr) > 1 else 0.0,
        "pos_rate": round(float((arr > 0).mean()), 4),
        "pred_px": round(cur_mid * (1 + med), 2),
    }


def role_study(role_terms, tagged, frames, intervals, min_points, max_stale_h):
    records = []
    for item in tagged:
        df = frames.get(item["id"])
        if df is None:
            continue
        cur_mid = float(df["mid"].iloc[-1])
        per_interval = {}
        for iv in intervals:
            vals = []
            for term in role_terms:
                try:
                    start_ts = pd.Timestamp(term["start"])
                except (ValueError, TypeError):
                    continue
                r = window_return(df, start_ts, iv, min_points, max_stale_h)
                if r is not None:
                    vals.append(r)
            if vals:
                per_interval[iv["id"]] = interval_stats(vals, cur_mid)
        if per_interval:
            records.append(
                {
                    "item_id": item["id"],
                    "label": item["label"],
                    "group": item.get("group"),
                    "mid": round(cur_mid, 2),
                    "intervals": per_interval,
                }
            )

    def sort_key(rec):
        for iv_id in ("day1", "pre", "post"):
            if iv_id in rec["intervals"]:
                return rec["intervals"][iv_id]["median"]
        return 0.0

    records.sort(key=sort_key, reverse=True)

    by_interval = {}
    for iv in intervals:
        meds = [r["intervals"][iv["id"]]["median"] for r in records if iv["id"] in r["intervals"]]
        pos = [r["intervals"][iv["id"]]["pos_rate"] for r in records if iv["id"] in r["intervals"]]
        if meds:
            by_interval[iv["id"]] = {
                "median": round(float(np.median(meds)), 5),
                "mean": round(float(np.mean(meds)), 5),
                "pos_rate": round(float(np.mean(pos)), 4),
                "n_items": len(meds),
            }
    return {"n_terms": len(role_terms), "by_interval": by_interval, "items": records}


def mayor_effect_study(terms, frames, watch, cfg=None, now=None):
    cfg = cfg if cfg is not None else (watch.get("effects") or {})
    intervals = cfg.get("intervals") or DEFAULT_INTERVALS
    min_points = int(cfg.get("min_points", 6))
    max_stale_h = float(cfg.get("max_stale_h", 48))

    by_mayor_items = {}
    for item in watch["items"]:
        for mid in item.get("mayors", []):
            by_mayor_items.setdefault(mid, []).append(item)

    mayors_out = {}
    for entry in watch.get("mayors", []):
        mid = entry["id"]
        tagged = by_mayor_items.get(mid, [])
        roles = {}
        for role in ("mayor", "minister"):
            role_terms = [
                t
                for t in terms
                if t.get(role) == mid and t.get("source") != "gap" and t.get("start")
            ]
            roles[role] = role_study(role_terms, tagged, frames, intervals, min_points, max_stale_h)
        mayors_out[mid] = {
            "id": mid,
            "name": entry.get("name", mid.title()),
            "tagline": entry.get("tagline"),
            "items": [it["id"] for it in tagged],
            "roles": roles,
        }

    return {
        "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "intervals": intervals,
        "min_points": min_points,
        "max_stale_h": max_stale_h,
        "mayors": mayors_out,
    }
