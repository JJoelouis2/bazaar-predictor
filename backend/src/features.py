import numpy as np
import pandas as pd

from common import (
    ELECTIONS_PATH,
    GRID_SECONDS,
    MINISTER_WEIGHT,
    load_calendar,
    load_item_rows,
    load_watchlist,
    read_jsonl,
)

FREQ = f"{GRID_SECONDS // 3600}h" if GRID_SECONDS % 3600 == 0 else f"{GRID_SECONDS}s"
STEPS_6H = 6 * 3600 // GRID_SECONDS
STEPS_24H = 24 * 3600 // GRID_SECONDS
LAGS = {1: "2h", 3: "6h", 6: "12h", 12: "24h", 36: "3d", 84: "7d"}
WINDOWS = {"24h": 12, "7d": 84, "30d": 360}
NUMERIC_COLS = ["instabuy", "instasell", "mid", "bv", "sv", "bws", "sws", "bo", "so"]


def load_terms(cal=None, elections_rows=None):
    cal = cal if cal is not None else load_calendar()
    terms = [dict(t) for t in cal["terms"]]
    if not elections_rows:
        elections_rows = read_jsonl(ELECTIONS_PATH)
    for row in sorted(elections_rows, key=lambda r: r["t"]):
        row_mayor = row.get("mayor_id") or row.get("mayor_key")
        row_minister = row.get("minister_id") or row.get("minister_key")
        for i, term in enumerate(terms):
            end = term.get("end")
            if term["start"] <= row["t"] and (end is None or row["t"] < end):
                if (
                    term.get("start", "9999") < row["t"]
                    and (
                        term.get("mayor") != row_mayor
                        or term.get("minister") != row_minister
                    )
                ):
                    new_term = {
                        "start": row["t"],
                        "end": end,
                        "year": None,
                        "mayor": row_mayor,
                        "mayor_name": row.get("mayor_name"),
                        "minister": row_minister,
                        "minister_name": row.get("minister_name"),
                        "source": "live",
                    }
                    terms[i]["end"] = row["t"]
                    terms.insert(i + 1, new_term)
                break
    terms.sort(key=lambda t: t["start"])
    return terms


def mayor_universe(terms):
    names = set()
    for term in terms:
        if term.get("mayor"):
            names.add(term["mayor"])
        if term.get("minister"):
            names.add(term["minister"])
    return sorted(names)


def event_feature_frame(terms, grid_index):
    starts = pd.to_datetime([t["start"] for t in terms], format="ISO8601")
    idx = np.searchsorted(starts.asi8, grid_index.asi8, side="right") - 1
    covered = idx >= 0
    idx_safe = np.clip(idx, 0, len(terms) - 1)
    start_arr = starts[idx_safe]
    end_vals = [t.get("end") for t in terms]
    ends = pd.to_datetime(["9999-12-31" if e is None else e for e in end_vals], format="ISO8601")
    end_arr = ends[idx_safe]
    mayor = np.array([terms[i].get("mayor") for i in idx_safe], dtype=object)
    minister = np.array([terms[i].get("minister") for i in idx_safe], dtype=object)
    mayor_name = np.array([terms[i].get("mayor_name") for i in idx_safe], dtype=object)
    minister_name = np.array([terms[i].get("minister_name") for i in idx_safe], dtype=object)
    source = np.array([terms[i].get("source") for i in idx_safe], dtype=object)
    labeled = covered & np.array([m is not None for m in mayor], dtype=bool)
    return {
        "covered": covered,
        "labeled": labeled,
        "start_arr": start_arr,
        "end_arr": end_arr,
        "mayor": mayor,
        "minister": minister,
        "mayor_name": mayor_name,
        "minister_name": minister_name,
        "source": source,
    }


def update_flags(updates, grid_index):
    flags = np.zeros(len(grid_index), dtype=float)
    for upd in updates or []:
        try:
            at = pd.to_datetime(upd.get("at"))
        except (ValueError, TypeError):
            continue
        if pd.isna(at):
            continue
        diff_h = np.abs((grid_index - at).total_seconds().to_numpy()) / 3600.0
        flags = np.maximum(flags, (diff_h <= 24).astype(float))
    return flags


def dense_frame(item_id):
    rows = load_item_rows(item_id)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"])
    df = df.sort_values("t").drop_duplicates("t", keep="last").set_index("t")
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan
    grid = pd.date_range(df.index.min(), df.index.max(), freq=FREQ)
    df = df.reindex(grid)
    present = df["mid"].notna()
    df["filled"] = (~present).astype(np.int8)
    last_real = pd.Series(df.index, index=df.index).where(present).ffill()
    df["stale_h"] = (df.index - last_real) / pd.Timedelta(hours=1)
    df = df.ffill()
    return df


def build_features(item_id, terms, updates=None, ref_ret=None, focus_ids=None):
    df = dense_frame(item_id)
    if df is None or len(df) < 200:
        return None
    grid_index = df.index
    ev = event_feature_frame(terms, grid_index)

    df["covered"] = ev["covered"].astype(np.int8)
    df["labeled"] = ev["labeled"].astype(np.int8)
    df["spread"] = (df["instabuy"] - df["instasell"]) / df["mid"]
    for lag, label in LAGS.items():
        df[f"ret_{label}"] = np.log(df["mid"] / df["mid"].shift(lag))
    for label, w in WINDOWS.items():
        min_p = max(6, w // 7)
        roll_mean = df["mid"].rolling(w, min_periods=min_p).mean()
        roll_std = df["mid"].rolling(w, min_periods=min_p).std()
        df[f"z_{label}"] = (df["mid"] - roll_mean) / roll_std
        df[f"mratio_{label}"] = df["mid"] / roll_mean
    df["log_sv"] = np.log1p(df["sv"])
    df["log_bv"] = np.log1p(df["bv"])
    df["sv_bv"] = df["sv"] / (df["bv"] + 1.0)
    df["sws_chg"] = df["sws"] / df["sws"].shift(12) - 1.0

    hour = grid_index.hour.to_numpy()
    dow = grid_index.dayofweek.to_numpy()
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)

    df["term_age"] = (grid_index - ev["start_arr"]) / pd.Timedelta(days=1)
    df["term_left"] = (ev["end_arr"] - grid_index) / pd.Timedelta(days=1)
    df["near_boundary"] = (
        (df["term_age"].abs() <= 0.5) | (df["term_left"].abs() <= 0.5)
    ).astype(np.int8)
    df["near_update"] = update_flags(updates, grid_index).astype(np.int8)

    for name in mayor_universe(terms):
        df[f"mayor_{name}"] = (ev["mayor"] == name).astype(float) * ev["covered"]
        df[f"minister_{name}"] = (ev["minister"] == name).astype(float) * MINISTER_WEIGHT * ev["covered"]
    if focus_ids:
        active = np.zeros(len(grid_index), dtype=float)
        for fid in focus_ids:
            active = np.maximum(
                active,
                np.where(ev["mayor"] == fid, 1.0, np.where(ev["minister"] == fid, MINISTER_WEIGHT, 0.0)),
            )
        df["focus_active"] = active * ev["covered"]

    if ref_ret is not None:
        aligned = ref_ret.reindex(grid_index)
        df["corr_ref_7d"] = (
            df["ret_6h"].rolling(84, min_periods=42).corr(aligned)
        )

    df["fwd_6h"] = np.log(df["mid"].shift(-STEPS_6H) / df["mid"])
    df["fwd_24h"] = np.log(df["mid"].shift(-STEPS_24H) / df["mid"])
    df["fwd_px_6h"] = df["mid"].shift(-STEPS_6H)
    df["fwd_px_24h"] = df["mid"].shift(-STEPS_24H)
    df["item_id"] = item_id
    return df


def build_all(cal=None):
    cal = cal if cal is not None else load_calendar()
    terms = load_terms(cal)
    updates = cal.get("updates", [])
    watch = load_watchlist()
    frames = {}
    for item in watch["items"]:
        focus_ids = item.get("mayors") or ([watch["mayor_focus"]] if watch.get("mayor_focus") else None)
        df = build_features(item["id"], terms, updates, ref_ret=None, focus_ids=focus_ids)
        if df is not None:
            frames[item["id"]] = df
    ref_id = "BOOSTER_COOKIE" if "BOOSTER_COOKIE" in frames else next(iter(frames), None)
    if ref_id:
        ref = frames[ref_id]["ret_6h"]
        for df in frames.values():
            aligned = ref.reindex(df.index)
            df["corr_ref_7d"] = df["ret_6h"].rolling(84, min_periods=42).corr(aligned)
    return frames


def main():
    frames = build_all()
    for item_id, df in sorted(frames.items()):
        print(f"{item_id}: rows={len(df)} cols={len(df.columns)} "
              f"span={df.index.min().date()}..{df.index.max().date()} "
              f"z30d_now={df['z_30d'].iloc[-1]:.2f}")


if __name__ == "__main__":
    main()
