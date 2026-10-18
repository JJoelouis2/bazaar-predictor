import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from analytics import compute_analytics, current_term
from common import (
    ELECTIONS_PATH,
    FRONTEND_DATA,
    GRID_SECONDS,
    load_calendar,
    load_json,
    load_watchlist,
    read_jsonl,
    save_json,
)
from features import build_all, load_terms

SERIES_DAYS_2H = 90
Z_WINDOW = "30d"


def downsample(df):
    recent_cut = df.index.max() - pd.Timedelta(days=SERIES_DAYS_2H)
    recent = df.loc[df.index >= recent_cut]
    older = df.loc[df.index < recent_cut]
    if len(older):
        daily = older.groupby(older.index.floor("D")).last()
        combined = pd.concat([daily, recent])
    else:
        combined = recent
    return combined.sort_index()


def series_payload(df):
    d = downsample(df)
    ma7 = df["mid"].rolling(84, min_periods=42).mean().reindex(d.index)
    ma30 = df["mid"].rolling(360, min_periods=180).mean().reindex(d.index)

    def rnd(arr, n):
        return [None if np.isnan(v) else round(float(v), n) for v in arr]

    return {
        "t": [str(t) for t in d.index],
        "mid": rnd(d["mid"].to_numpy(), 2),
        "ib": rnd(d["instabuy"].to_numpy(), 2),
        "is": rnd(d["instasell"].to_numpy(), 2),
        "z": rnd(d[f"z_{Z_WINDOW}"].to_numpy(), 3),
        "ma7": rnd(ma7.to_numpy(), 2),
        "ma30": rnd(ma30.to_numpy(), 2),
        "sv": rnd(d["sv"].to_numpy(), 0),
        "bv": rnd(d["bv"].to_numpy(), 0),
    }


def change(df, steps):
    if len(df) <= steps:
        return None
    past = float(df["mid"].iloc[-steps - 1])
    now = float(df["mid"].iloc[-1])
    return None if past <= 0 else round(now / past - 1, 5)


def items_payload(frames, watch, predictions, analytics):
    alert_ids = {a["item_id"] for a in analytics["alerts"]}
    mom = {m["item_id"]: m for m in analytics["momentum"]}
    preds = predictions.get("items", {}) if predictions else {}
    out = []
    for item in watch["items"]:
        item_id = item["id"]
        df = frames.get(item_id)
        if df is None:
            continue
        m = mom.get(item_id, {})
        p = preds.get(item_id, {})
        out.append(
            {
                "id": item_id,
                "label": item["label"],
                "group": item["group"],
                "sector": item["sector"],
                "mayors": item.get("mayors", []),
                "t": str(df.index[-1]),
                "mid": round(float(df["mid"].iloc[-1]), 2),
                "instabuy": round(float(df["instabuy"].iloc[-1]), 2),
                "instasell": round(float(df["instasell"].iloc[-1]), 2),
                "change_24h": change(df, 12),
                "change_7d": change(df, 84),
                "z_30d": m.get("z_30d"),
                "z_7d": m.get("z_7d"),
                "spread": m.get("spread"),
                "trend_24h": m.get("trend_24h"),
                "accel_24h": m.get("accel_24h"),
                "pct_from_7d_high": m.get("pct_from_7d_high"),
                "pct_from_7d_low": m.get("pct_from_7d_low"),
                "corr_ref_7d": m.get("corr_ref_7d"),
                "liquidity": round(float(df["sv"].iloc[-1] + df["bv"].iloc[-1]), 0),
                "alert": item_id in alert_ids,
                "stale_h": p.get("stale_h"),
                "pred_pct_h6": p.get("pred_pct_h6"),
                "pred_px_h6": p.get("pred_px_h6"),
                "skill_h6": p.get("skill_h6"),
                "dir_acc_h6": p.get("dir_acc_h6"),
                "pred_pct_h24": p.get("pred_pct_h24"),
                "pred_px_h24": p.get("pred_px_h24"),
                "skill_h24": p.get("skill_h24"),
                "dir_acc_h24": p.get("dir_acc_h24"),
            }
        )
    return out


def events_payload(terms, calendar):
    slim = []
    for t in terms:
        slim.append(
            {
                "start": t["start"],
                "end": t.get("end"),
                "mayor": t.get("mayor"),
                "mayor_name": t.get("mayor_name"),
                "minister": t.get("minister"),
                "minister_name": t.get("minister_name"),
                "source": t.get("source"),
                "year": t.get("year"),
                "votes": t.get("votes"),
            }
        )
    election_rows = read_jsonl(ELECTIONS_PATH)
    live = election_rows[-1] if election_rows else None
    return {
        "terms": slim,
        "current": current_term(terms),
        "live": live,
        "minister_weight": calendar.get("minister_weight"),
        "updates": calendar.get("updates", []),
    }


def mayors_payload(watch, items_out):
    by_mayor = {}
    for item in items_out:
        for mid in item.get("mayors", []):
            by_mayor.setdefault(mid, []).append(item["id"])
    out = []
    seen = set()
    for entry in watch.get("mayors", []):
        mid = entry["id"]
        seen.add(mid)
        out.append(
            {
                "id": mid,
                "name": entry.get("name", mid.title()),
                "phase": entry.get("phase"),
                "tagline": entry.get("tagline"),
                "items": by_mayor.get(mid, []),
                "active": bool(by_mayor.get(mid)),
            }
        )
    for mid, ids in by_mayor.items():
        if mid not in seen:
            out.append(
                {
                    "id": mid,
                    "name": mid.title(),
                    "phase": None,
                    "tagline": None,
                    "items": ids,
                    "active": True,
                }
            )
    return out


def main():
    watch = load_watchlist()
    calendar = load_calendar()
    terms = load_terms(calendar)
    frames = build_all(calendar)
    analytics = compute_analytics(frames=frames, terms=terms, watch=watch)

    predictions = None
    pred_path = FRONTEND_DATA / "predictions.json"
    if pred_path.exists():
        predictions = load_json(pred_path)

    FRONTEND_DATA.mkdir(parents=True, exist_ok=True)
    series_dir = FRONTEND_DATA / "series"
    series_dir.mkdir(parents=True, exist_ok=True)

    keep = set()
    sparks = {}
    for item in watch["items"]:
        df = frames.get(item["id"])
        if df is None:
            continue
        save_json(series_dir / f"{item['id']}.json", series_payload(df))
        keep.add(f"{item['id']}.json")
        tail = df["mid"].tail(48)
        sparks[item["id"]] = [None if np.isnan(v) else round(float(v), 1) for v in tail]
    for f in series_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    save_json(FRONTEND_DATA / "sparks.json", sparks)

    items_out = items_payload(frames, watch, predictions, analytics)
    save_json(FRONTEND_DATA / "items.json", items_out)
    save_json(FRONTEND_DATA / "mayors.json", mayors_payload(watch, items_out))
    save_json(FRONTEND_DATA / "analytics.json", analytics)
    save_json(FRONTEND_DATA / "events.json", events_payload(terms, calendar))
    save_json(
        FRONTEND_DATA / "meta.json",
        {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phase": watch.get("phase"),
            "phase_label": watch.get("phase_label"),
            "mayor_focus": watch.get("mayor_focus"),
            "grid_seconds": GRID_SECONDS,
            "horizons": ["h6", "h24"],
            "z_threshold": analytics["z_threshold"],
            "series_days_2h": SERIES_DAYS_2H,
            "attributions": [
                {"name": "Hypixel API", "url": "https://api.hypixel.net"},
                {"name": "Coflnet Bazaar History", "url": "https://sky.coflnet.com"},
                {"name": "SkyblockElections", "url": "https://skyblockelections.com"},
                {"name": "Hypixel Skyblock Wiki", "url": "https://hypixelskyblock.minecraft.wiki"},
            ],
        },
    )
    print(
        f"built frontend data: items={len(watch['items'])} series={len(keep)} "
        f"alerts={len(analytics['alerts'])} -> {FRONTEND_DATA}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
