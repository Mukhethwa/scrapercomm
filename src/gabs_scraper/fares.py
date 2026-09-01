"""Scrape the Gold Card multi-journey fares and map them onto our stops.

https://www.gabs.co.za/MultiJourneyFares.aspx publishes one table per origin, each row a
destination with a product code and three prices. Fares are quoted between *fare zones* -
broad places like "Cape Town" or "Mitchells Plain" - not between the 527 timing points we
hold, so loading them is two jobs: read the table, then decide which of our stops each
zone stands for.

What the products actually are, from the operator's own product page. The names are
misleading and the arithmetic depends on it:

    Five Ride    5 rides,  valid 15 days
    Weekly      10 rides,  valid 30 days      <- not a week
    Monthly     48 rides,  valid 90 days      <- not a month

So a single ride costs five_ride / 5, and the longer products are only cheaper per ride.
None of them varies by time of day. Cash fares do - peak runs 16:00 to 08:00 - but the
operator publishes no cash fare per journey, so nothing here can state one.

Money is kept in cents. A price that has been through a float is a bug waiting to be
found by a customer.
"""
from __future__ import annotations

import argparse
import html as H
import re
from datetime import datetime, timezone

import requests

from . import db
from .config import Settings

FARES_URL = "https://www.gabs.co.za/MultiJourneyFares.aspx"

# Rides each product carries, straight off the product page.
RIDES = {"five_ride": 5, "weekly": 10, "monthly": 48}

_DDL = """
CREATE TABLE IF NOT EXISTS fare (
    origin_zone       TEXT NOT NULL,
    destination_zone  TEXT NOT NULL,
    code              TEXT NOT NULL,
    five_ride_cents   INTEGER,
    weekly_cents      INTEGER,
    monthly_cents     INTEGER,
    transfers         TEXT,
    scraped_at        TIMESTAMPTZ,
    PRIMARY KEY (origin_zone, destination_zone)
);
CREATE INDEX IF NOT EXISTS fare_code_idx ON fare (code);

-- Which of our stops a fare zone stands for. A zone usually covers several: the fare to
-- "Cape Town" is the fare to every timing point we hold in town.
CREATE TABLE IF NOT EXISTS fare_zone_stop (
    zone      TEXT NOT NULL,
    stop_id   INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    via       TEXT NOT NULL,
    PRIMARY KEY (zone, stop_id)
);
CREATE INDEX IF NOT EXISTS fare_zone_stop_stop_idx ON fare_zone_stop (stop_id);
"""

# Zones whose name shares no usable words with the stop we hold for them. Everything else
# is matched mechanically; this is only the tail that cannot be.
ALIASES = {
    "University of the Western Cape": "UWC",
    "City": "CAPE TOWN",
    "Koeberg Station": "KOEBERG STN",
    "Koeberg Power Station": "KOEBERG POWER STN",
    "Parow Station": "PAROW",
    "Steenberg Station": "STEENBERG STN",
    "Tygerberg Station": "TYGERBERG STN",
    "De Waal Road": "DE WAAL RD",
}

# Some zones name a place we simply hold no timing point for - "Mitchells Plain",
# "Kirstenbosch", "Seaforth". They stay unmapped on purpose rather than being pointed at
# a stop that is merely nearby; a wrong fare is worse than no fare.

# Words our timetables abbreviate. Expanded on both sides before comparing.
ABBREV = {
    "STN": "STATION", "IND": "INDUSTRIA", "INDUS": "INDUSTRIA",
    "PLN": "PLAIN", "RD": "ROAD", "DRV": "DRIVE", "AVE": "AVENUE",
    "STH": "SOUTH", "NTH": "NORTH", "PK": "PARK", "CIR": "CIRCLE",
    "HOSP": "HOSPITAL", "CRES": "CRESCENT", "SQ": "SQUARE", "CTR": "CENTRE",
}

_ROW = re.compile(
    r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td>"
    r"<td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>")
_HEAD = re.compile(r'<div style\s*=\s*"padding-left:18px"\s*>([^<]+?)\s*to\s*</div>', re.I)

_QUALIFIER = re.compile(r"\((?:VIA|V)[^)]*\)|\bVIA\b.*$", re.I)


def cents(price: str) -> int | None:
    """"R1 008.00" -> 100800. Thousands are split by a space, sometimes non-breaking."""
    cleaned = re.sub(r"[^0-9.]", "", price.replace("\xa0", " "))
    if not cleaned:
        return None
    rands, _, frac = cleaned.partition(".")
    return int(rands or 0) * 100 + int((frac + "00")[:2])


def fetch(session=None) -> str:
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", Settings().user_agent)
    r = session.get(FARES_URL, timeout=60)
    r.raise_for_status()
    return r.text


def parse(html: str) -> list[dict]:
    """Every (origin, destination) row on the page, prices already in cents."""
    heads = [(m.start(), H.unescape(m.group(1)).strip()) for m in _HEAD.finditer(html)]
    out: list[dict] = []
    for i, (pos, origin) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(html)
        for m in _ROW.finditer(html[pos:end]):
            dest, code, five, week, month, transfers = (
                H.unescape(x).strip() for x in m.groups())
            out.append({
                "origin_zone": origin, "destination_zone": dest, "code": code,
                "five_ride_cents": cents(five), "weekly_cents": cents(week),
                "monthly_cents": cents(month), "transfers": transfers,
            })
    return out


def _squash(name: str) -> str:
    """Letters only, so "Blue Downs", "BLUEDOWNS" and "Blue-Downs" all compare equal.

    The timetables and the fare page disagree constantly about whether a place name is
    one word or two - BLUEDOWNS vs Blue Downs, SUMMER GREENS vs Summergreens, SEA FORTH
    vs Seaforth - and none of that is a real difference.
    """
    return re.sub(r"[^A-Z0-9]", "", _QUALIFIER.sub(" ", name.upper()))


def _tokens(name: str) -> list[str]:
    """Comparable words: no route qualifier, no punctuation, abbreviations expanded."""
    s = _QUALIFIER.sub(" ", name.upper())
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return [ABBREV.get(t, t) for t in s.split() if t]


def _zone_labels(zone: str) -> list[str]:
    """One zone can name two places: "Athlone / Athlone Industria"."""
    body = _QUALIFIER.sub(" ", zone)
    return [p.strip() for p in body.split("/") if p.strip()] or [zone]


def map_zones(conn, zones: list[str]) -> list[tuple[str, int, str]]:
    """Decide which stops each fare zone covers. Returns (zone, stop_id, how)."""
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM stop")
    stops = [(i, n, _tokens(n)) for i, n in cur.fetchall()]
    by_exact = {n.upper(): i for i, n, _ in stops}
    by_squash: dict[str, list[int]] = {}
    for i, n, _ in stops:
        by_squash.setdefault(_squash(n), []).append(i)

    pairs: list[tuple[str, int, str]] = []
    for zone in zones:
        hits: list[tuple[int, str]] = []
        alias = ALIASES.get(zone)
        if alias and alias.upper() in by_exact:
            hits.append((by_exact[alias.upper()], "alias"))
        if not hits:
            for label in _zone_labels(zone):
                if label.upper() in by_exact:
                    hits.append((by_exact[label.upper()], "exact"))
                    continue
                for sid in by_squash.get(_squash(label), []):
                    hits.append((sid, "spacing"))
                if hits:
                    continue
                want = _tokens(label)
                if not want:
                    continue
                for sid, _name, have in stops:
                    if len(have) == len(want) and all(
                            a == b or a.startswith(b) or b.startswith(a)
                            for a, b in zip(have, want)):
                        hits.append((sid, "abbrev"))
                if hits:
                    continue
                # A zone is a place, and we often hold several timing points inside it:
                # "Hout Bay" covers HOUT BAY BEACH, HARBOUR and MAIN RD. Matching on the
                # leading words picks up all of them, and the fare is the same to each.
                for sid, _name, have in stops:
                    if len(have) > len(want) and all(
                            a == b for a, b in zip(have[:len(want)], want)):
                        hits.append((sid, "within"))
        seen: set[int] = set()
        for sid, how in hits:
            if sid not in seen:
                seen.add(sid)
                pairs.append((zone, sid, how))
    return pairs


def ensure_tables(conn) -> None:
    cur = conn.cursor()
    for stmt in filter(str.strip, _DDL.split(";")):
        cur.execute(stmt)
    conn.commit()


def load(conn, rows: list[dict]) -> dict:
    ensure_tables(conn)
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    for r in rows:
        cur.execute(
            """
            INSERT INTO fare (origin_zone, destination_zone, code, five_ride_cents,
                              weekly_cents, monthly_cents, transfers, scraped_at)
            VALUES (%(origin_zone)s, %(destination_zone)s, %(code)s, %(five_ride_cents)s,
                    %(weekly_cents)s, %(monthly_cents)s, %(transfers)s, %(now)s)
            ON CONFLICT (origin_zone, destination_zone) DO UPDATE SET
                code=EXCLUDED.code, five_ride_cents=EXCLUDED.five_ride_cents,
                weekly_cents=EXCLUDED.weekly_cents, monthly_cents=EXCLUDED.monthly_cents,
                transfers=EXCLUDED.transfers, scraped_at=EXCLUDED.scraped_at
            """,
            {**r, "now": now},
        )

    zones = sorted({r["origin_zone"] for r in rows} | {r["destination_zone"] for r in rows})
    pairs = map_zones(conn, zones)
    cur.execute("DELETE FROM fare_zone_stop")
    for zone, stop_id, how in pairs:
        cur.execute(
            "INSERT INTO fare_zone_stop (zone, stop_id, via) VALUES (%s,%s,%s) "
            "ON CONFLICT (zone, stop_id) DO UPDATE SET via=EXCLUDED.via",
            (zone, stop_id, how),
        )
    conn.commit()

    mapped = {z for z, _, _ in pairs}
    return {
        "fares": len(rows),
        "zones": len(zones),
        "zones_mapped": len(mapped),
        "zones_unmapped": sorted(set(zones) - mapped),
        "stop_links": len(pairs),
    }


def scrape() -> dict:
    rows = parse(fetch())
    if not rows:
        raise SystemExit("no fare rows parsed - the page layout has probably changed")
    conn = db.connect()
    try:
        return load(conn, rows)
    finally:
        conn.close()


if __name__ == "__main__":
    argparse.ArgumentParser(description="Scrape Gold Card multi-journey fares").parse_args()
    stats = scrape()
    print(f"fares={stats['fares']} zones={stats['zones']} "
          f"mapped={stats['zones_mapped']} stop_links={stats['stop_links']}")
    if stats["zones_unmapped"]:
        print(f"unmapped zones ({len(stats['zones_unmapped'])}):")
        for z in stats["zones_unmapped"]:
            print("   ", z)
