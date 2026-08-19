from pathlib import Path

import pytest

from gabs_scraper import db, load, parse
from gabs_scraper.download import DownloadResult
from gabs_scraper.harvest import entry_from_pdf_path

SAMPLES = Path(__file__).parent / "samples"

# A synthetic filename/number (999999) so the test never collides with — or
# deletes — a real timetable in a populated database. The PDF *content* parsed is
# a real sample; only the entry metadata is synthetic.
TEST_PATH = "Pdf/Apdf/ZZZ_TEST___SAMPLE_from_20260622_to_99999999_999999.pdf"
TEST_FILENAME = TEST_PATH.split("/")[-1]
TEST_ROUTE = "ZZZ TEST-SAMPLE"


@pytest.fixture()
def conn():
    try:
        c = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {e}")
    yield c
    cur = c.cursor()
    cur.execute("DELETE FROM timetable WHERE pdf_filename = %s", (TEST_FILENAME,))
    cur.execute(
        "DELETE FROM route WHERE name = %s "
        "AND NOT EXISTS (SELECT 1 FROM timetable WHERE route_id = route.id)",
        (TEST_ROUTE,),
    )
    c.commit()
    c.close()


def _count(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def test_load_sample_and_idempotent(conn):
    entry = entry_from_pdf_path(TEST_PATH)
    parsed = parse.parse_pdf(str(SAMPLES / "NYANGA_AIRPORT_BELLVILLE_004401.pdf"))
    dl = DownloadResult(entry.pdf_filename, "x", "deadbeef", 100, ok=True)

    tid = load.load_timetable(conn, entry, dl, parsed)
    cur = conn.cursor()

    assert _count(cur, "SELECT count(*) FROM schedule WHERE timetable_id=%s", (tid,)) >= 2

    # A known departure: BELLVILLE at 06:05 on the weekday schedule.
    got = _count(
        cur,
        """
        SELECT count(*) FROM stop_time st
        JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
        JOIN stop s          ON s.id  = ss.stop_id
        JOIN schedule sc     ON sc.id = ss.schedule_id
        WHERE sc.timetable_id = %s AND s.name = 'BELLVILLE'
          AND st.departure_time = '06:05'
        """,
        (tid,),
    )
    assert got >= 1

    stop_times_sql = (
        "SELECT count(*) FROM stop_time st "
        "JOIN trip t ON t.id = st.trip_id "
        "JOIN schedule sc ON sc.id = t.schedule_id "
        "WHERE sc.timetable_id = %s"
    )
    before = _count(cur, stop_times_sql, (tid,))
    assert before > 0

    # Reload is idempotent: same timetable id, same child counts.
    tid2 = load.load_timetable(conn, entry, dl, parsed)
    assert tid2 == tid
    assert _count(cur, stop_times_sql, (tid,)) == before


def test_notes_loaded(conn):
    entry = entry_from_pdf_path(TEST_PATH)
    parsed = parse.parse_pdf(str(SAMPLES / "NYANGA_AIRPORT_BELLVILLE_004401.pdf"))
    tid = load.load_timetable(conn, entry, None, parsed)
    cur = conn.cursor()
    cur.execute(
        "SELECT description FROM timetable_note WHERE timetable_id=%s AND code='a'",
        (tid,),
    )
    row = cur.fetchone()
    assert row and row[0] == "Mondays,Tuesdays,Wednesdays,Thursdays"
