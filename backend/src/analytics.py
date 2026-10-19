import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from common import GRID_SECONDS, load_watchlist, save_json, TEMP_DATA
from features import build_all, load_terms

Z_THRESHOLD = 3.0
CORR_WINDOW = 84 * 3  # 90d of 2h steps
ALERT_SCAN_DAYS = 90


def current_alerts(df, item_id, labels):
    label = labels.get(item_id, item_id)
    z = float(df["z_30d"].iloc[-1])
    if abs(z) < Z_THRESHOLD:
        return None
    return {
        "item_id": item_id,
        "label": label,
        "z": round(z, 3),
        "mid": float(df["mid"].iloc[-1]),
        "instabuy": float(df["instabuy"].iloc[-1]),
        "instasell": float(df["instasell"].iloc[-1]),
        "stale_h": round(float(df["stale_h"].iloc[-1]), 2),
        "t": str(df.index[-1]),
        "direction": "up" if z > 0 else "down",
    }


def alert_events(df, item_id, lookback_steps):
    z = df["z_30d"].tail(lookback_steps)
    events = []
    prev_z = None
    for t, val in z.items():
        if np.isnan(val):
            continue
        if abs(val) >= Z_THRESHOLD and (prev_z is None or abs(prev_z) < Z_THRESHOLD):
            events.append(
                {
                    "item_id": item_id,
                    "t": str(t),
                    "z": round(float(val), 3),
                    "mid": float(df["mid"].loc[t]),
                    "direction": "up" if val > 0 else "down",
                }
            )
        prev_z = val
    return events


def momentum(df, item_id):
    trend = np.log(df["mid"] / df["mid"].shift(12))
    accel = trend - trend.shift(12)
    roll_max = df["mid"].rolling(84, min_periods=42).max()
    roll_min = df["mid"].rolling(84, min_periods=42).min()
    return {
        "item_id": item_id,
        "trend_24h": round(float(trend.iloc[-1]), 5),
        "accel_24h": round(float(accel.iloc[-1]), 5),
        "z_30d": round(float(df["z_30d"].iloc[-1]), 3),
        "z_7d": round(float(df["z_7d"].iloc[-1]), 3),
        "pct_from_7d_high": round(float(df["mid"].iloc[-1] / roll_max.iloc[-1] - 1), 5),
        "pct_from_7d_low": round(float(df["mid"].iloc[-1] / roll_min.iloc[-1] - 1), 5),
        "corr_ref_7d": (
            None
            if np.isnan(df["corr_ref_7d"].iloc[-1])
            else round(float(df["corr_ref_7d"].iloc[-1]), 4)
        ),
        "spread": round(float(df["spread"].iloc[-1]), 5),
    }


def correlation_matrix(frames, ids):
    rets = pd.DataFrame({i: frames[i]["ret_6h"] for i in ids})
    z = pd.DataFrame({i: frames[i]["z_30d"] for i in ids})
    rets = rets.where(np.abs(z) <= Z_THRESHOLD)
    rets = rets.tail(CORR_WINDOW)
    corr = rets.corr(min_periods=42)
    matrix = []
    for a in ids:
        row = []
        for b in ids:
            val = corr.loc[a, b]
            row.append(None if np.isnan(val) else round(float(val), 4))
        matrix.append(row)
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            val = corr.loc[a, b]
            if not np.isnan(val):
                pairs.append({"a": a, "b": b, "corr": round(float(val), 4)})
    pairs.sort(key=lambda p: abs(p["corr"]), reverse=True)
    neighbors = {}
    for a in ids:
        ranked = sorted(
            ({"item": b, "corr": corr.loc[a, b]} for b in ids if b != a),
            key=lambda p: abs(p["corr"]),
            reverse=True,
        )
        neighbors[a] = [
            {"item": p["item"], "corr": round(float(p["corr"]), 4)}
            for p in ranked[:3]
            if not np.isnan(p["corr"])
        ]
    return {"items": ids, "matrix": matrix, "top_pairs": pairs[:15], "neighbors": neighbors}


def term_day1_effects(frames, terms, mayor_id, item_ids):
    effects = []
    for term in terms:
        if term.get("mayor") != mayor_id:
            continue
        start = pd.Timestamp(term["start"])
        for item_id in item_ids:
            df = frames.get(item_id)
            if df is None:
                continue
            window = df.loc[(df.index >= start) & (df.index <= start + pd.Timedelta(days=2))]
            if len(window) < 6:
                continue
            p0 = float(window["mid"].iloc[0])
            p1 = float(window["mid"].iloc[12]) if len(window) > 12 else float(window["mid"].iloc[-1])
            effects.append(
                {
                    "year": term.get("year"),
                    "item_id": item_id,
                    "start": term["start"],
                    "pct_24h": round(p1 / p0 - 1, 5),
                }
            )
    return effects


def mayor_active_mask(df, mayor_id):
    mcol = f"mayor_{mayor_id}"
    ncol = f"minister_{mayor_id}"
    if mcol in df.columns:
        return (df[mcol] > 0) | (df.get(ncol, 0) > 0)
    return df["focus_active"] > 0


def focus_analysis_for(frames, terms, mayor_id, tagged):
    per_item = []
    for item in tagged:
        df = frames.get(item["id"])
        if df is None:
            continue
        ret = df["ret_24h"]
        active = mayor_active_mask(df, mayor_id)
        base = (df["labeled"] == 1) & (~active) & (df["stale_h"] < 48)
        a_vals = ret[active].dropna()
        b_vals = ret[base].dropna()
        if len(a_vals) < 10 or len(b_vals) < 100:
            continue
        per_item.append(
            {
                "item_id": item["id"],
                "label": item["label"],
                "n_active": int(len(a_vals)),
                "n_base": int(len(b_vals)),
                "abs_ret_active": round(float(a_vals.abs().mean()), 6),
                "abs_ret_base": round(float(b_vals.abs().mean()), 6),
                "vol_ratio": round(float(a_vals.abs().mean() / b_vals.abs().mean()), 4),
                "mean_ret_active": round(float(a_vals.mean()), 6),
                "mean_ret_base": round(float(b_vals.mean()), 6),
            }
        )
    item_ids = [i["id"] for i in tagged]
    effects = term_day1_effects(frames, terms, mayor_id, item_ids)
    ratios = [p["vol_ratio"] for p in per_item]
    day1 = [e["pct_24h"] for e in effects]
    n_mayor_terms = sum(1 for t in terms if t.get("mayor") == mayor_id and t.get("source") != "gap")
    n_minister_terms = sum(1 for t in terms if t.get("minister") == mayor_id and t.get("source") != "gap")
    return {
        "mayor": mayor_id,
        "per_item": per_item,
        "day1_effects": effects,
        "aggregate": {
            "n_mayor_terms": n_mayor_terms,
            "n_minister_terms": n_minister_terms,
            "median_vol_ratio": None if not ratios else round(float(np.median(ratios)), 4),
            "mean_day1_pct": None if not day1 else round(float(np.mean(day1)), 5),
            "median_day1_pct": None if not day1 else round(float(np.median(day1)), 5),
        },
    }


def focus_analysis(frames, terms, watch):
    by_mayor = {}
    for item in watch["items"]:
        for mid in item.get("mayors", []):
            by_mayor.setdefault(mid, []).append(item)
    out = {}
    for mid, tagged in by_mayor.items():
        out[mid] = focus_analysis_for(frames, terms, mid, tagged)
    return out


def current_term(terms, now=None):
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    term = None
    for t in terms:
        if t["start"] <= now and (t.get("end") is None or now < t["end"]):
            term = t
    if term is None:
        return None
    end = term.get("end")
    return {
        "start": term["start"],
        "end": end,
        "mayor": term.get("mayor_name"),
        "mayor_id": term.get("mayor"),
        "minister": term.get("minister_name"),
        "minister_id": term.get("minister"),
        "year": term.get("year"),
        "days_left": None if end is None else round((pd.Timestamp(end) - pd.Timestamp(now)).days, 2),
        "source": term.get("source"),
    }


def compute_analytics(frames=None, terms=None, watch=None):
    watch = watch or load_watchlist()
    terms = terms if terms is not None else load_terms()
    frames = frames if frames is not None else build_all()
    labels = {i["id"]: i["label"] for i in watch["items"]}
    ids = [i["id"] for i in watch["items"] if i["id"] in frames]

    lookback = int(ALERT_SCAN_DAYS * 86400 / GRID_SECONDS)
    alerts = []
    history = []
    for item_id in ids:
        df = frames[item_id]
        a = current_alerts(df, item_id, labels)
        if a:
            alerts.append(a)
        history.extend(alert_events(df, item_id, lookback))
    history.sort(key=lambda e: e["t"], reverse=True)

    mom = [momentum(frames[i], i) for i in ids]
    focus_map = focus_analysis(frames, terms, watch)
    default_focus = watch.get("mayor_focus")
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "z_threshold": Z_THRESHOLD,
        "alerts": sorted(alerts, key=lambda a: abs(a["z"]), reverse=True),
        "alert_history": history[:40],
        "momentum": mom,
        "correlations": correlation_matrix(frames, ids),
        "focus": focus_map.get(default_focus) or next(iter(focus_map.values()), None),
        "focus_by_mayor": focus_map,
        "current_term": current_term(terms),
    }
    return out


def main():
    out = compute_analytics()
    path = TEMP_DATA / "analytics_preview.json"
    save_json(path, out)
    print(f"alerts={len(out['alerts'])} history={len(out['alert_history'])}")
    agg = (out.get("focus") or {}).get("aggregate")
    print("focus aggregate:", json.dumps(agg))
    print("current term:", json.dumps(out["current_term"]))
    print(f"saved {path}")


if __name__ == "__main__":
    main()
