import argparse
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import xgboost as xgb
from statsmodels.tsa.statespace.sarimax import SARIMAX

from common import MODELS_DIR, GRID_SECONDS, load_watchlist, save_json
from features import build_all

HORIZONS = {"h6": ("fwd_6h", 6 * 3600 // GRID_SECONDS), "h24": ("fwd_24h", 24 * 3600 // GRID_SECONDS)}
EXCLUDE = {"item_id", "fwd_px_6h", "fwd_px_24h"}
MIN_ROWS = 500


def feature_cols(df):
    return [
        c
        for c in df.columns
        if c not in EXCLUDE and not str(c).startswith("fwd_") and df[c].dtype.kind in "fiu"
    ]


def prepare(df, target_col, window_days):
    cutoff = df.index.max() - pd.Timedelta(days=window_days)
    d = df.loc[df.index >= cutoff].copy()
    d = d[d["stale_h"] <= 48]
    d = d.dropna(subset=[target_col])
    return d


def split_points(n):
    test_n = max(int(n * 0.1), 12)
    train_n = n - test_n
    val_n = max(int(train_n * 0.15), 12)
    return train_n - val_n, train_n


def regression_metrics(pred, actual):
    mae = float(np.mean(np.abs(pred - actual)))
    mae_naive = float(np.mean(np.abs(actual)))
    mape = float(np.mean(np.abs(np.exp(pred) - np.exp(actual)) / np.exp(actual)))
    nonzero = np.abs(actual) > 1e-6
    dir_acc = (
        None
        if nonzero.sum() == 0
        else float(np.mean(np.sign(pred[nonzero]) == np.sign(actual[nonzero])))
    )
    return {
        "mae": round(mae, 6),
        "mae_naive": round(mae_naive, 6),
        "skill": round(1 - mae / mae_naive, 4) if mae_naive > 0 else None,
        "mape": round(mape, 5),
        "dir_acc": None if dir_acc is None else round(dir_acc, 4),
        "n_test": int(len(actual)),
    }


def train_xgb(d, cols, target_col):
    X = d[cols].to_numpy(np.float32)
    y = d[target_col].to_numpy(np.float32)
    tr_end, tr_full = split_points(len(d))
    model = xgb.XGBRegressor(
        n_estimators=600,
        learning_rate=0.05,
        max_depth=6,
        min_child_weight=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=2.0,
        early_stopping_rounds=40,
        eval_metric="mae",
        n_jobs=4,
    )
    model.fit(
        X[:tr_end],
        y[:tr_end],
        eval_set=[(X[tr_end:tr_full], y[tr_end:tr_full])],
        verbose=False,
    )
    pred = model.predict(X[tr_full:])
    metrics = regression_metrics(pred.astype(float), y[tr_full:].astype(float))
    metrics["n_train"] = int(tr_full)
    return model, metrics


def sarimax_block(d, target_col, steps):
    endog = np.log(d["mid"].to_numpy())
    exog_cols = [c for c in ("focus_active", "labeled") if c in d.columns]
    exog = d[exog_cols].to_numpy(float) if exog_cols else None
    _, tr_full = split_points(len(d))
    n = len(d)
    origins = list(range(tr_full, n - steps, max(steps, 6)))
    if len(origins) < 5:
        return None
    preds, actuals = [], []
    try:
        base = SARIMAX(
            endog[:tr_full],
            exog=exog[:tr_full] if exog is not None else None,
            order=(1, 1, 0),
            trend="c",
        ).fit(disp=False, maxiter=100)
        res = base
        cursor = tr_full
        for origin in origins:
            if origin > cursor:
                res = res.append(
                    endog[cursor:origin],
                    exog=exog[cursor:origin] if exog is not None else None,
                )
                cursor = origin
            fc = res.get_forecast(
                steps=steps,
                exog=exog[origin : origin + steps] if exog is not None else None,
            )
            pred_px = float(np.exp(fc.predicted_mean[-1]))
            origin_t = d.index[origin]
            target_t = d.index[min(origin + steps, n - 1)]
            act_px = float(d["mid"].loc[target_t])
            origin_px = float(d["mid"].loc[origin_t])
            preds.append(np.log(pred_px / origin_px))
            actuals.append(np.log(act_px / origin_px))
    except Exception as err:
        return {"error": str(err)[:200], "n_origins": len(origins)}
    metrics = regression_metrics(np.array(preds), np.array(actuals))
    metrics["n_origins"] = len(origins)
    metrics["order"] = [1, 1, 0]
    metrics["exog"] = exog_cols or []
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=730)
    parser.add_argument("--items", nargs="*", default=None)
    args = parser.parse_args()

    watch = load_watchlist()
    frames = build_all()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "window_days": args.window_days, "items": {}}
    all_metrics = {}
    failures = []

    for item in watch["items"]:
        item_id = item["id"]
        if args.items and item_id not in args.items:
            continue
        df = frames.get(item_id)
        if df is None or len(df) < MIN_ROWS:
            print(f"{item_id}: SKIP (rows={0 if df is None else len(df)} < {MIN_ROWS})")
            continue
        cols = feature_cols(df)
        entry = {}
        for hname, (target_col, steps) in HORIZONS.items():
            d = prepare(df, target_col, args.window_days)
            if len(d) < 200:
                entry[hname] = {"skipped": f"too few rows after prep: {len(d)}"}
                continue
            try:
                model, m_xgb = train_xgb(d, cols, target_col)
                model_path = MODELS_DIR / f"{item_id}__{hname}.json"
                model.save_model(str(model_path))
                m_sarimax = sarimax_block(d, target_col, steps)
                entry[hname] = {"xgb": m_xgb, "sarimax": m_sarimax}
                entry[hname]["xgb"]["file"] = model_path.name
                entry[hname]["xgb"]["cols"] = cols
                entry[hname]["xgb"]["rows"] = int(len(d))
                entry[hname]["xgb"]["test_start"] = str(d.index[-entry[hname]["xgb"]["n_test"]])
                print(
                    f"{item_id} {hname}: skill={m_xgb['skill']} mape={m_xgb['mape']} "
                    f"dir={m_xgb['dir_acc']} n_test={m_xgb['n_test']} "
                    f"sarimax_skill={(m_sarimax or {}).get('skill')}"
                )
            except Exception as err:
                entry[hname] = {"error": str(err)[:300]}
                failures.append(f"{item_id}/{hname}")
                print(f"{item_id} {hname}: FAILED {err}", file=sys.stderr)
        if entry:
            all_metrics[item_id] = entry
            manifest["items"][item_id] = entry

    save_json(MODELS_DIR / "manifest.json", manifest)
    save_json(MODELS_DIR / "metrics.json", all_metrics)
    print(f"saved manifest+metrics to {MODELS_DIR}")
    if failures:
        print(f"ERROR failures: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
