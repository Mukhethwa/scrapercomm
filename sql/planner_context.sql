-- The timetable's own arithmetic, worked out once instead of on every search.
--
-- Golden Arrow prints a time at timing points and "via" everywhere else: 291 of 629 stops
-- never get a printed departure. Both the planner and the journeys-with-a-change search
-- work around that the same way - a bus cannot reach you before it left the last stop it
-- does have a time for, so that time is a floor, and the next printed time is a ceiling.
--
-- Each of those queries computed it with a window over every departure of every trip that
-- touches the stop being searched. From a hub like CAPE TOWN that is hundreds of thousands
-- of rows, recomputed on every request, which is most of why a journey with a change took
-- tens of seconds in town while the app gives up at thirty.
--
-- It is a pure function of the loaded timetable, so it belongs in a table. A materialised
-- view rather than a hand-filled one: the definition IS the arithmetic, so the copy cannot
-- drift from the query it replaces.
--
-- Rebuild it after every load - gabs_scraper.context --fix, which the refresh scripts run.
-- Stale, it would answer with the last load's floors, so the loaders own it.

DROP MATERIALIZED VIEW IF EXISTS trip_stop_context;

CREATE MATERIALIZED VIEW trip_stop_context AS
SELECT st.trip_id,
       ss.stop_sequence,
       -- The last printed time at or before this stop, and where it was printed. max()
       -- and min() ignore NULLs, so a run of vias reaches back to the last real time.
       max(st.departure_time) OVER w_before                                   AS prior_time,
       min(st.departure_time) OVER w_after                                    AS next_time,
       max(CASE WHEN st.departure_time IS NOT NULL THEN ss.stop_sequence END)
           OVER w_before                                                      AS prior_seq,
       min(CASE WHEN st.departure_time IS NOT NULL THEN ss.stop_sequence END)
           OVER w_after                                                       AS next_seq
FROM stop_time st
JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
WHERE st.cell_type <> 'NONE'
WINDOW w_before AS (PARTITION BY st.trip_id ORDER BY ss.stop_sequence
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
       w_after  AS (PARTITION BY st.trip_id ORDER BY ss.stop_sequence
                    ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING);

-- Unique, so REFRESH MATERIALIZED VIEW CONCURRENTLY is allowed: a rebuild then leaves the
-- old rows readable while it works, and a search during a refresh answers from them
-- rather than waiting or failing.
CREATE UNIQUE INDEX IF NOT EXISTS trip_stop_context_pkey
    ON trip_stop_context (trip_id, stop_sequence);
