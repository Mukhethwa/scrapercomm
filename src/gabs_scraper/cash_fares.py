"""The cash fares Golden Arrow actually publishes.

    PYTHONPATH=src python -m gabs_scraper.cash_fares --dry-run
    PYTHONPATH=src python -m gabs_scraper.cash_fares

Everything else in this project prices a journey from the Gold Card table, because that is
what MultiJourneyFares.aspx publishes: 5 Ride, Weekly, Monthly. Divide the five-ride price
by five and you have the card fare, which is what the app has been showing - correctly
labelled, and not what most riders pay. Most riders pay cash.

CASH CANNOT BE DERIVED FROM THE CARD FARE, and the operator's own numbers prove it rather
than merely suggest it. From the August 2025 fare notice:

    5-ride R215.00   ->  cash R52.50  (Atlantis to Cape Town)
                     and cash R85.50  (Darling to Cape Town)
    5-ride R126.50   ->  cash R34.50, R41.50 and R44.50
    5-ride R116.00   ->  cash R30.00  and R41.50

Two journeys the operator charges the same card price for differ by 63% in cash. Across the
21 published routes the ratio of cash to card-per-ride runs from 1.21 to 1.99. So there is
no percentage, no multiplier and no lookup from the card price that yields a cash fare -
and it gets worse where GO Easy applies, because that fare is FLAT: one price from anywhere
to anywhere, carrying no information about distance at all, while the whole point of a cash
fare is that it varies with distance.

What can be had is the twenty-one routes the fare notice prints in full, which is what this
loads. They cover the busiest corridors - Khayelitsha to Cape Town, Bellville to Cape Town,
Cape Town to Wynberg and Mitchells Plain - and nothing else, because nothing else is
published. The notice says so itself: "For a full list of revised fares, please contact the
Transport Information Centre on 0800 65 64 63."

TWO THINGS THE APP MUST SAY OUT LOUD about every number this loads.

It is dated. These take effect 11 August 2025 and are the most recent cash fares Golden
Arrow has published; the card fares moved again in August 2026, so these are one increase
behind and a rider will likely be charged a little more.

It carries no time of day. The Gold Card FAQ says cash fares differ by when you travel -
"Peak period starts at 16:00 and ends at 08:00" - and the notice prints one cash figure per
route with no peak or off-peak split. So this is the published cash fare and not a promise
about what a given bus will charge at a given hour.
"""
from __future__ import annotations

import argparse
import collections
import io
import re
import urllib.request
from datetime import date

from . import db

NOTICE_URL = ("https://www.gabs.co.za/Assets/press/pressreleases/"
              "MEDIA%20RELEASE%202502_Fares%20increase%20August%202025.pdf")

# When the fares this loads took effect. Shown to the rider, because a year-old fare is
# worth having and is not worth mistaking for today's.
EFFECTIVE_FROM = date(2025, 8, 11)

# The routes are printed as areas, and our fare zones use slightly different names.
# Mapped by hand because there are twenty-one of them and a fuzzy match that puts the
# Koeberg power station in Koeberg Road would be wrong about money.
ZONE_ALIASES = {
    "Koeberg Power Station/Melkbos": "Koeberg Power Station",
    "Blue Downs to Claremont/Rondebosch": "Claremont",
    "Claremont/Rondebosch": "Claremont",
    "Century City/Montague Gnds": "Century City",
    "Mitchell's Plain": "Mitchells Plain",
    "Mitchell’s Plain": "Mitchells Plain",
}

_DDL = """
CREATE TABLE IF NOT EXISTS cash_fare (
    origin_zone       TEXT NOT NULL,
    destination_zone  TEXT NOT NULL,
    cash_cents        INTEGER NOT NULL,
    effective_from    DATE NOT NULL,
    source_url        TEXT NOT NULL,
    scraped_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_zone, destination_zone)
);
"""

_MONEY = re.compile(r"\d[\d\s]*\.\d\d")


def rows_from_pdf(data: bytes) -> list[tuple[str, int, int]]:
    """
    (route, cash cents, five-ride cents) for every row of the notice.

    The table is rendered rotated - 1,675 of the page's 1,682 characters report
    upright=False - so pdfplumber finds no table and its text comes out interleaved by
    column, one letter of every route name at a time. Reading the characters back by
    position, grouped across the page and ordered along it, puts the rows together again.
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        chars = [c for page in pdf.pages for c in page.chars if not c.get("upright")]

    lines: dict[int, list] = collections.defaultdict(list)
    for c in chars:
        lines[round(c["top"] / 6)].append(c)

    out = []
    for key in sorted(lines):
        text = "".join(c["text"] for c in sorted(lines[key], key=lambda c: c["x0"]))
        money = [float(m.replace(" ", "")) for m in _MONEY.findall(text)]
        # Current and New for each of cash, 5-ride, weekly, monthly. A row with any other
        # count is a heading, or the pensioner line, whose cash fare is "n/a".
        if len(money) != 8:
            continue
        name = text[:_MONEY.search(text).start()].strip()
        if name:
            out.append((name, round(money[1] * 100), round(money[3] * 100)))
    return out


def split_route(route: str) -> tuple[str, str] | None:
    """"Bellville to Cape Town" -> the two fare zones, as our tables spell them."""
    parts = re.split(r"\s+to\s+", route, maxsplit=1)
    if len(parts) != 2:
        return None
    return tuple(ZONE_ALIASES.get(p.strip(), p.strip()) for p in parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Load the published cash fares")
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    ap.add_argument("--url", default=NOTICE_URL)
    args = ap.parse_args()

    print(f"reading {args.url.rsplit('/', 1)[-1]}", flush=True)
    req = urllib.request.Request(args.url, headers={"User-Agent": "commuttr-fares"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()

    rows = rows_from_pdf(data)
    print(f"  {len(rows)} routes with a published cash fare\n")

    conn = None if args.dry_run else db.connect()
    try:
        if conn:
            cur = conn.cursor()
            cur.execute(_DDL)

        kept = skipped = 0
        for route, cash_cents, five_cents in rows:
            zones = split_route(route)
            if not zones:
                print(f"  skip  {route}: cannot tell which two areas this is between")
                skipped += 1
                continue
            origin, destination = zones
            ratio = cash_cents / (five_cents / 5)
            print(f"  {origin:<24} -> {destination:<28} "
                  f"cash R{cash_cents / 100:>6.2f}   (card per ride "
                  f"R{five_cents / 500:>5.2f}, x{ratio:.2f})")
            kept += 1
            if conn:
                cur.execute(
                    """
                    INSERT INTO cash_fare (origin_zone, destination_zone, cash_cents,
                                           effective_from, source_url)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (origin_zone, destination_zone) DO UPDATE SET
                        cash_cents = EXCLUDED.cash_cents,
                        effective_from = EXCLUDED.effective_from,
                        source_url = EXCLUDED.source_url,
                        scraped_at = now()
                    """,
                    (origin, destination, cash_cents, EFFECTIVE_FROM, args.url),
                )
        if conn:
            conn.commit()

        print(f"\n{kept} cash fares {'read' if args.dry_run else 'stored'}"
              + (f", {skipped} skipped" if skipped else ""))
        print("Every other journey has no published cash fare. Golden Arrow says so in the "
              "notice\nitself: for the full list, phone the Transport Information Centre "
              "on 0800 65 64 63.")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
