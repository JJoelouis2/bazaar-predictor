import argparse
import sys

from common import (
    ELECTIONS_PATH,
    HYPIXEL_BAZAAR_URL,
    HYPIXEL_ELECTION_URL,
    align_grid,
    append_jsonl,
    history_path,
    http_get_json,
    iso,
    normalize_prices,
    now_utc,
    read_jsonl,
    watchlist_ids,
)


def collect_bazaar():
    data = http_get_json(HYPIXEL_BAZAAR_URL)
    products = data.get("products") or {}
    t = iso(align_grid(now_utc()))
    rows = []
    missing = []
    for item_id in watchlist_ids():
        product = products.get(item_id)
        if not product:
            missing.append(item_id)
            continue
        qs = product.get("quick_status") or {}
        instabuy = float(qs.get("buyPrice") or 0)
        instasell = float(qs.get("sellPrice") or 0)
        row = {
            "t": t,
            "instabuy": instabuy,
            "instasell": instasell,
            "mid": (instabuy + instasell) / 2,
            "bv": float(qs.get("buyVolume") or 0),
            "sv": float(qs.get("sellVolume") or 0),
            "bws": float(qs.get("buyMovingWeek") or 0),
            "sws": float(qs.get("sellMovingWeek") or 0),
            "bo": int(qs.get("buyOrders") or 0),
            "so": int(qs.get("sellOrders") or 0),
        }
        normalize_prices(row)
        rows.append((item_id, row))
    return t, rows, missing


def collect_election():
    data = http_get_json(HYPIXEL_ELECTION_URL)
    mayor = data.get("mayor") or {}
    minister = mayor.get("minister") or {}
    current = data.get("current") or {}
    candidates = [
        {"key": c.get("key"), "name": c.get("name")}
        for c in (current.get("candidates") or [])
    ]
    row = {
        "t": iso(align_grid(now_utc())),
        "mayor_id": (mayor.get("name") or "").lower(),
        "mayor_name": mayor.get("name"),
        "minister_id": (minister.get("name") or "").lower(),
        "minister_name": minister.get("name"),
        "mayor_key": mayor.get("key"),
        "minister_key": minister.get("key"),
        "election_year": current.get("year"),
        "candidates": candidates,
    }
    existing = read_jsonl(ELECTIONS_PATH)
    if existing:
        last = existing[-1]
        changed = (
            last.get("mayor_id") != row["mayor_id"]
            or last.get("minister_id") != row["minister_id"]
            or last.get("election_year") != row["election_year"]
        )
        if not changed:
            return None
    append_jsonl(ELECTIONS_PATH, [row])
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-election", action="store_true")
    args = parser.parse_args()

    t, rows, missing = collect_bazaar()
    for item_id, row in rows:
        append_jsonl(history_path(item_id), [row])
    print(f"bazaar t={t} items={len(rows)} missing={missing}")

    if not args.skip_election:
        e = collect_election()
        if e:
            print(f"election change t={e['t']} mayor={e['mayor_name']} minister={e['minister_name']} year={e['election_year']}")
        else:
            print("election unchanged")

    if missing:
        print(f"ERROR: missing watchlist products: {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
