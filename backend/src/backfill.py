import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

from common import (
    COFLNET_HISTORY_URL,
    align_grid,
    dedupe_by_t,
    history_path,
    http_get_json,
    load_item_rows,
    load_watchlist,
    normalize_prices,
    parse_iso,
    write_jsonl,
)

DEFAULT_START = "2020-06-01"


def fetch_chunk(item_id, start, end):
    url = COFLNET_HISTORY_URL.format(tag=item_id)
    data = http_get_json(
        url,
        params={
            "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        timeout=60,
    )
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected response for {item_id} {start}: {str(data)[:200]}")
    rows = []
    for point in data:
        buy = float(point.get("buy") or 0)
        sell = float(point.get("sell") or 0)
        if buy <= 0 or sell <= 0:
            continue
        t = align_grid(parse_iso(point["timestamp"]))
        row = {
            "t": t.strftime("%Y-%m-%dT%H:%M:%S"),
            "instabuy": buy,
            "instasell": sell,
            "mid": (buy + sell) / 2,
            "bv": float(point.get("buyVolume") or 0),
            "sv": float(point.get("sellVolume") or 0),
            "bws": float(point.get("buyMovingWeek") or 0),
            "sws": float(point.get("sellMovingWeek") or 0),
        }
        normalize_prices(row)
        rows.append(row)
    return rows


def chunks(start, end, chunk_days):
    cur = start
    step = timedelta(days=chunk_days)
    while cur < end:
        nxt = min(cur + step, end)
        yield cur, nxt
        cur = nxt


def backfill_item(item_id, start, end, chunk_days, sleep_s, pause_every):
    merged = {row["t"]: row for row in load_item_rows(item_id)}
    n_new = 0
    n_requests = 0
    for i, (c0, c1) in enumerate(chunks(start, end, chunk_days)):
        rows = fetch_chunk(item_id, c0, c1)
        n_requests += 1
        for row in rows:
            if row["t"] not in merged:
                n_new += 1
            merged[row["t"]] = row
        if pause_every and n_requests % pause_every == 0:
            time.sleep(20)
        time.sleep(sleep_s)
    write_jsonl(history_path(item_id), [merged[k] for k in sorted(merged)])
    return n_new, n_requests, len(merged)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None, help="YYYY-MM-DD (default: now)")
    parser.add_argument("--chunk-days", type=int, default=7)
    parser.add_argument("--sleep", type=float, default=0.75)
    parser.add_argument("--pause-every", type=int, default=60, help="extra pause after N requests")
    parser.add_argument("--items", nargs="*", default=None)
    parser.add_argument("--only", default=None, help="backfill a single item id")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc)

    if args.only:
        items = [args.only]
    elif args.items:
        items = args.items
    else:
        items = [item["id"] for item in load_watchlist()["items"]]

    failures = []
    for idx, item_id in enumerate(items, 1):
        try:
            n_new, n_req, n_total = backfill_item(
                item_id, start, end, args.chunk_days, args.sleep, args.pause_every
            )
            print(
                f"[{idx}/{len(items)}] {item_id}: new={n_new} requests={n_req} total_rows={n_total}",
                flush=True,
            )
        except Exception as err:
            print(f"[{idx}/{len(items)}] {item_id}: FAILED {err}", file=sys.stderr, flush=True)
            failures.append(item_id)

    if failures:
        print(f"ERROR: {len(failures)} items failed: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
