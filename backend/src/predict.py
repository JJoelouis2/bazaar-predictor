import sys
from datetime import datetime, timezone

import numpy as np
import xgboost as xgb

from common import FRONTEND_DATA, MODELS_DIR, load_json, save_json
from features import build_all

HORIZONS = ("h6", "h24")


def load_model(path):
    model = xgb.XGBRegressor()
    model.load_model(str(path))
    return model


def main():
    manifest_path = MODELS_DIR / "manifest.json"
    if not manifest_path.exists():
        print("ERROR: no manifest, run train.py first", file=sys.stderr)
        return 1
    manifest = load_json(manifest_path)
    frames = build_all()
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models_trained_at": manifest.get("trained_at"),
        "items": {},
    }
    for item_id, entry in manifest.get("items", {}).items():
        df = frames.get(item_id)
        if df is None or not len(df):
            continue
        last = df.iloc[[-1]]
        row = {
            "t": str(df.index[-1]),
            "mid": round(float(df["mid"].iloc[-1]), 4),
            "instabuy": round(float(df["instabuy"].iloc[-1]), 4),
            "instasell": round(float(df["instasell"].iloc[-1]), 4),
            "z_30d": None
            if np.isnan(df["z_30d"].iloc[-1])
            else round(float(df["z_30d"].iloc[-1]), 3),
            "spread": round(float(df["spread"].iloc[-1]), 5),
            "stale_h": round(float(df["stale_h"].iloc[-1]), 2),
        }
        for hname in HORIZONS:
            block = (entry.get(hname) or {}).get("xgb") or {}
            model_file = block.get("file")
            if not model_file:
                continue
            model = load_model(MODELS_DIR / model_file)
            X = last[block["cols"]].to_numpy(np.float32)
            pred = float(model.predict(X)[0])
            row[f"pred_pct_{hname}"] = round(pred, 5)
            row[f"pred_px_{hname}"] = round(row["mid"] * float(np.exp(pred)), 2)
            row[f"skill_{hname}"] = block.get("skill")
            row[f"dir_acc_{hname}"] = block.get("dir_acc")
            row[f"mape_{hname}"] = block.get("mape")
        out["items"][item_id] = row

    FRONTEND_DATA.mkdir(parents=True, exist_ok=True)
    save_json(FRONTEND_DATA / "predictions.json", out)
    print(f"predictions for {len(out['items'])} items -> {FRONTEND_DATA / 'predictions.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
