"""Load parsed timetables into PostgreSQL.

A timetable is keyed on its unique PDF filename (a "version"). Loading is
idempotent: the timetable row is upserted and its child rows (schedules, stops,
trips, stop_times, notes) are replaced inside one transaction, so re-running the
pipeline never duplicates data.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from .download import DownloadResult
from .harvest import ManifestEntry
from .parse import ParsedTimetable


def _to_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _to_time(s: str | None) -> time | None:
    if not s:
        return None
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def _upsert_route(cur, entry: ManifestEntry) -> int:
    cur.execute(
        """
        INSERT INTO route (name, origin, destination, letter_group)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            origin = EXCLUDED.origin,
            destination = EXCLUDED.destination,
            letter_group = EXCLUDED.letter_group
        RETURNING id
        """,
        (entry.route_name, entry.origin, entry.destination, entry.letter_group),
    )
    return cur.fetchone()[0]


def _get_or_create_stop(cur, cache: dict[str, int], name: str) -> int:
    if name in cache:
        return cache[name]
    cur.execute(
        "INSERT INTO stop (name) VALUES (%s) "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        (name,),
    )
    sid = cur.fetchone()[0]
    cache[name] = sid
    return sid


def _upsert_timetable(
    cur,
    route_id: int,
    entry: ManifestEntry,
    dl: DownloadResult | None,
    parsed: ParsedTimetable | None,
    status: str,
    error: str | None,
) -> int:
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO timetable (
            route_id, timetable_number, is_public_holiday,
            effective_from, effective_to, pdf_url, pdf_filename, pdf_sha256,
            page_count, raw_text, parse_status, parse_error, scraped_at, parsed_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (pdf_filename) DO UPDATE SET
            route_id = EXCLUDED.route_id,
            timetable_number = EXCLUDED.timetable_number,
            is_public_holiday = EXCLUDED.is_public_holiday,
            effective_from = EXCLUDED.effective_from,
            effective_to = EXCLUDED.effective_to,
            pdf_url = EXCLUDED.pdf_url,
            pdf_sha256 = EXCLUDED.pdf_sha256,
            page_count = EXCLUDED.page_count,
            raw_text = EXCLUDED.raw_text,
            parse_status = EXCLUDED.parse_status,
            parse_error = EXCLUDED.parse_error,
            scraped_at = EXCLUDED.scraped_at,
            parsed_at = EXCLUDED.parsed_at
        RETURNING id
        """,
        (
            route_id,
            (parsed.timetable_number if parsed else None) or entry.timetable_number,
            entry.is_public_holiday,
            _to_date(entry.effective_from),
            _to_date(entry.effective_to),
            entry.pdf_url,
            entry.pdf_filename,
            dl.sha256 if dl else None,
            parsed.page_count if parsed else None,
            parsed.raw_text if parsed else None,
            status,
            error,
            now,
            now if status == "parsed" else None,
        ),
    )
    return cur.fetchone()[0]


def load_failed(
    conn, entry: ManifestEntry, dl: DownloadResult | None, error: str
) -> int:
    cur = conn.cursor()
    route_id = _upsert_route(cur, entry)
    tid = _upsert_timetable(cur, route_id, entry, dl, None, "failed", error)
    cur.execute("DELETE FROM schedule WHERE timetable_id = %s", (tid,))
    cur.execute("DELETE FROM timetable_note WHERE timetable_id = %s", (tid,))
    conn.commit()
    return tid


def load_timetable(
    conn,
    entry: ManifestEntry,
    dl: DownloadResult | None,
    parsed: ParsedTimetable,
) -> int:
    cur = conn.cursor()
    route_id = _upsert_route(cur, entry)
    tid = _upsert_timetable(cur, route_id, entry, dl, parsed, "parsed", None)

    # Replace children (schedule cascades to schedule_stop/trip/stop_time).
    cur.execute("DELETE FROM schedule WHERE timetable_id = %s", (tid,))
    cur.execute("DELETE FROM timetable_note WHERE timetable_id = %s", (tid,))

    for n in parsed.notes:
        cur.execute(
            "INSERT INTO timetable_note (timetable_id, code, description) "
            "VALUES (%s, %s, %s) ON CONFLICT (timetable_id, code) DO NOTHING",
            (tid, n.code, n.description),
        )

    stop_cache: dict[str, int] = {}
    for s in parsed.schedules:
        cur.execute(
            """
            INSERT INTO schedule (
                timetable_id, page_number, direction_index, direction_label,
                day_type, day_label, section_timetable_number,
                section_effective_date, no_service
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (
                tid, s.page_number, s.direction_index, s.direction_label,
                s.day_type, s.day_label, s.section_timetable_number,
                _to_date(s.section_effective_date), s.no_service,
            ),
        )
        schedule_id = cur.fetchone()[0]

        sstop_ids: list[int] = []
        for seq, stop_name in enumerate(s.stops):
            stop_id = _get_or_create_stop(cur, stop_cache, stop_name)
            cur.execute(
                "INSERT INTO schedule_stop (schedule_id, stop_id, stop_sequence) "
                "VALUES (%s, %s, %s) RETURNING id",
                (schedule_id, stop_id, seq),
            )
            sstop_ids.append(cur.fetchone()[0])

        for t in s.trips:
            cur.execute(
                "INSERT INTO trip (schedule_id, trip_index, note_codes) "
                "VALUES (%s, %s, %s) RETURNING id",
                (schedule_id, t.trip_index, t.note_codes or None),
            )
            trip_id = cur.fetchone()[0]
            rows = [
                (
                    trip_id, sstop_ids[j], st.cell_type,
                    _to_time(st.departure_time), st.note_code, st.raw_value,
                )
                for j, st in enumerate(t.times)
            ]
            if rows:
                cur.executemany(
                    "INSERT INTO stop_time (trip_id, schedule_stop_id, cell_type, "
                    "departure_time, note_code, raw_value) VALUES (%s,%s,%s,%s,%s,%s)",
                    rows,
                )

    conn.commit()
    return tid
