import argparse
import re
from datetime import datetime, timedelta, timezone

import requests

from common import CONFIG_DIR, MINISTER_WEIGHT, load_json, save_json

WIKI_MODULE_URL = (
    "https://hypixelskyblock.minecraft.wiki/w/Module:Mayor/Elections/Data?action=raw"
)
COFLNET_ELECTIONS_URL = "https://skyblockelections-api.onrender.com/api/stored-elections"
SPECIAL_MAYORS = {"derpy", "jerry", "scorpius", "dante", "aura", "technoblade", "barry", "nancy", "faith", "seraphine"}

ANCHOR_YEAR = 519
ANCHOR_DATE = "2026-10-15T11:15:00"
ANCHOR_SOURCE = "skyblock.tools poll-close time for year 519 election, cross-checked vs Hypixel API mayor=Diaz on 2026-10-17"

BLOCK_RE = re.compile(r"\[(\d+)\]\s*=\s*\{")
DATE_RE = re.compile(r'date\s*=\s*"([^"]+)"')
NAME_RE = r'name\s*=\s*"([^"]+)"'
MAYOR_RE = re.compile(r"mayor\s*=\s*\{\s*" + NAME_RE)
MINISTER_RE = re.compile(r"minister\s*=\s*\{\s*" + NAME_RE)
CANDIDATE_RE = re.compile(
    r"(\w+)\s*=\s*\{perks=\{[^}]*\}(?:,params=\{[^}]*\})?,\s*votes=(\d+),\s*order=(\d+)"
)


def fetch_text(url):
    resp = requests.get(url, headers={"User-Agent": "bazaar-predictor/1.0"}, timeout=60)
    resp.raise_for_status()
    return resp.text


def fetch_json(url):
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def split_blocks(text):
    matches = list(BLOCK_RE.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((int(m.group(1)), text[start:end]))
    return blocks


def parse_wiki_elections(text):
    rows = []
    for year, body in split_blocks(text):
        date_m = DATE_RE.search(body)
        mayor_m = MAYOR_RE.search(body)
        if not date_m or not mayor_m:
            continue
        try:
            date = datetime.strptime(date_m.group(1), "%b %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        minister_m = MINISTER_RE.search(body)
        rows.append(
            {
                "year": year,
                "date": date,
                "mayor": mayor_m.group(1).lower(),
                "mayor_name": mayor_m.group(1),
                "minister": minister_m.group(1).lower() if minister_m else None,
                "minister_name": minister_m.group(1) if minister_m else None,
                "source": "wiki_module",
            }
        )
    rows.sort(key=lambda r: r["year"])
    return rows


def year_length_days(wiki_rows, anchor_date):
    last = wiki_rows[-1]
    a = datetime.strptime(anchor_date[:10], "%Y-%m-%d")
    b = datetime.strptime(last["date"], "%Y-%m-%d")
    return (a - b).days / (ANCHOR_YEAR - last["year"])


def parse_coflnet_elections(entries, year_len, anchor_dt):
    rows = []
    for entry in entries:
        year = entry.get("year")
        candidates = entry.get("candidates") or []
        if not year or not candidates:
            continue
        ranked = sorted(candidates, key=lambda c: c.get("votes", 0), reverse=True)
        winner = ranked[0]
        mayor_name = winner.get("name", "")
        if not mayor_name:
            continue
        mayor = mayor_name.lower()
        minister_entry = ranked[1] if len(ranked) > 1 else None
        if mayor in SPECIAL_MAYORS:
            minister_entry = None
        start = anchor_dt - timedelta(days=(ANCHOR_YEAR - year) * year_len)
        rows.append(
            {
                "year": year,
                "date": start.strftime("%Y-%m-%d"),
                "mayor": mayor,
                "mayor_name": mayor_name,
                "minister": minister_entry["name"].lower() if minister_entry else None,
                "minister_name": minister_entry["name"] if minister_entry else None,
                "votes": {c.get("name"): c.get("votes", 0) for c in candidates},
                "source": "derived_interpolation",
            }
        )
    rows.sort(key=lambda r: r["year"])
    return rows


def build_terms(rows, year_len):
    terms = []
    for i, row in enumerate(rows):
        if i + 1 == len(rows):
            end = None
        elif rows[i + 1]["year"] == row["year"] + 1:
            end = rows[i + 1]["date"]
        else:
            end_dt = datetime.strptime(row["date"], "%Y-%m-%d") + timedelta(days=year_len)
            end = end_dt.strftime("%Y-%m-%d")
            terms.append(
                {
                    "start": end,
                    "end": rows[i + 1]["date"],
                    "year": None,
                    "mayor": None,
                    "mayor_name": None,
                    "minister": None,
                    "minister_name": None,
                    "source": "gap",
                    "years_covered": [row["year"] + 1, rows[i + 1]["year"] - 1],
                }
            )
        term = {
            "start": row["date"],
            "end": end,
            "year": row["year"],
            "mayor": row["mayor"],
            "mayor_name": row["mayor_name"],
            "minister": row["minister"],
            "minister_name": row["minister_name"],
            "source": row["source"],
        }
        if "votes" in row:
            term["votes"] = row["votes"]
        terms.append(term)
    return terms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(CONFIG_DIR / "event_calendar.json"))
    args = parser.parse_args()

    wiki_text = fetch_text(WIKI_MODULE_URL)
    wiki_rows = parse_wiki_elections(wiki_text)
    year_len = year_length_days(wiki_rows, ANCHOR_DATE)
    anchor_dt = datetime.strptime(ANCHOR_DATE, "%Y-%m-%dT%H:%M:%S")

    cofl_entries = fetch_json(COFLNET_ELECTIONS_URL)
    derived_rows = parse_coflnet_elections(cofl_entries, year_len, anchor_dt)

    seen = set()
    rows = []
    for row in wiki_rows + derived_rows:
        if row["year"] in seen:
            continue
        seen.add(row["year"])
        rows.append(row)
    rows.sort(key=lambda r: r["year"])

    existing_updates = []
    try:
        existing = load_json(args.out)
        existing_updates = existing.get("updates", [])
    except FileNotFoundError:
        pass

    calendar = {
        "minister_weight": MINISTER_WEIGHT,
        "sources": {
            "wiki_module": WIKI_MODULE_URL,
            "coflnet_elections": COFLNET_ELECTIONS_URL,
            "interpolation_anchor": {"year": ANCHOR_YEAR, "date": ANCHOR_DATE, "note": ANCHOR_SOURCE},
            "year_length_days": round(year_len, 4),
        },
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "terms": build_terms(rows, year_len),
        "updates": existing_updates,
    }
    save_json(args.out, calendar)

    gaps = [t["years_covered"] for t in calendar["terms"] if t["source"] == "gap"]
    n_wiki = sum(1 for t in calendar["terms"] if t["source"] == "wiki_module")
    n_derived = sum(1 for t in calendar["terms"] if t["source"] == "derived_interpolation")
    print(
        f"terms={len(calendar['terms'])} wiki={n_wiki} derived={n_derived} "
        f"year_len={year_len:.3f}d gaps={gaps} span={calendar['terms'][0]['start']}->{calendar['terms'][-1]['start']}"
    )


if __name__ == "__main__":
    main()
