package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.Stop;
import org.springframework.data.jpa.repository.JpaRepository;
import za.co.commuttr.api.repo.projection.Projections.ThreeLegRow;
import za.co.commuttr.api.repo.projection.Projections.TwoLegRow;

import java.util.List;

/**
 * Journeys that need a change of bus.
 *
 * <p>The direct planner answers "which single bus goes from A to B". These answer "and if
 * none does, what do I catch instead". Both queries follow the same shape:
 *
 * <ol>
 *   <li>narrow to interchange candidates first — stops reachable from the origin that
 *       also reach the destination. That set is tiny (single figures to low hundreds) and
 *       costs milliseconds, and bounding the leg searches by it is the difference between
 *       a 10-second query and an 80-millisecond one;</li>
 *   <li>build each leg from real trips, keeping one representative row per physical
 *       service and time via {@code DISTINCT ON}. Without it the same connection repeats
 *       once per timetable version, exactly as the direct planner would without its
 *       grouping;</li>
 *   <li>join the legs on a shared interchange, matching day type, allowing a minimum
 *       time to change buses.</li>
 * </ol>
 *
 * <p><b>Every leg moves forward in time.</b> A leg's arrival must be later than its
 * departure. Without that condition the between-leg checks alone were satisfied by a
 * bus that "arrived" hours before it left, and because results are ordered by total
 * journey time those impossible connections sorted straight to the top. The cost is
 * that a leg genuinely crossing midnight is excluded, which is the safer trade.
 *
 * <p><b>Which times must exist.</b> Only 28% of timetable cells carry a published time;
 * 19% are "via", meaning the bus passes but the timetable gives no time. So a leg's
 * departure and its arrival <em>at an interchange</em> must be real times — you cannot
 * plan a change you cannot time — but arrival at the final destination may be "via",
 * because for many stops that is all Golden Arrow publishes. Requiring a time there
 * finds nothing for a large part of the network.
 */
@Repository
public interface ConnectionRepository extends JpaRepository<Stop, Integer> {

    @Query(value = """
            WITH ix AS (
                SELECT DISTINCT b.stop_id AS id
                FROM schedule_stop a
                JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                                    AND b.stop_sequence > a.stop_sequence
                WHERE a.stop_id = :fromId
                INTERSECT
                SELECT DISTINCT a.stop_id
                FROM schedule_stop a
                JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                                    AND b.stop_sequence > a.stop_sequence
                WHERE b.stop_id = :toId
            ),
            leg1 AS (
                SELECT DISTINCT ON (sc.day_type, ssb.stop_id, sc.direction_label,
                                    t1.departure_time, t2.departure_time)
                       sc.day_type, ssb.stop_id AS x, sc.direction_label AS route, tt.timetable_number AS ttn,
                       t1.departure_time AS dep, t1.raw_value AS dep_raw,
                       t2.departure_time AS arr,
                       sc.id AS sched, tr.trip_index AS trip,
                       ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
                FROM schedule_stop ssa
                JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                                      AND ssb.stop_sequence > ssa.stop_sequence
                JOIN schedule sc  ON sc.id = ssa.schedule_id
                JOIN timetable tt ON tt.id = sc.timetable_id
                JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
                JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                                 AND t1.cell_type <> 'NONE'
                JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                                 AND t2.cell_type = 'TIME'
                                 AND (t1.departure_time IS NULL
                                      OR t2.departure_time > t1.departure_time)
                WHERE ssa.stop_id = :fromId AND ssb.stop_id IN (SELECT id FROM ix)
                ORDER BY sc.day_type, ssb.stop_id, sc.direction_label,
                         t1.departure_time, t2.departure_time, sc.id, tr.trip_index
            ),
            leg2 AS (
                SELECT DISTINCT ON (sc.day_type, ssa.stop_id, sc.direction_label,
                                    t1.departure_time, t2.raw_value)
                       sc.day_type, ssa.stop_id AS x, sc.direction_label AS route, tt.timetable_number AS ttn,
                       t1.departure_time AS dep, t2.raw_value AS arr_raw,
                       t2.departure_time AS arr_time,
                       sc.id AS sched, tr.trip_index AS trip,
                       ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
                FROM schedule_stop ssa
                JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                                      AND ssb.stop_sequence > ssa.stop_sequence
                JOIN schedule sc  ON sc.id = ssa.schedule_id
                JOIN timetable tt ON tt.id = sc.timetable_id
                JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
                JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                                 AND t1.cell_type = 'TIME'
                JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                                 AND t2.cell_type <> 'NONE'
                                 AND (t2.departure_time IS NULL
                                      OR t2.departure_time > t1.departure_time)
                WHERE ssb.stop_id = :toId AND ssa.stop_id IN (SELECT id FROM ix)
                ORDER BY sc.day_type, ssa.stop_id, sc.direction_label,
                         t1.departure_time, t2.raw_value, sc.id, tr.trip_index
            )
            SELECT DISTINCT ON (COALESCE(l1.dep, l2.arr_time))
                   l1.day_type          AS "dayType",
                   x.id                 AS "changeId",
                   x.name               AS "changeName",
                   l1.route             AS "route1",
                   l1.ttn               AS "ttn1",
                   l1.dep               AS "dep1",
                   l1.dep_raw           AS "depRaw1",
                   l1.arr               AS "arr1",
                   l1.sched             AS "sched1",
                   l1.trip              AS "trip1",
                   l1.from_seq          AS "fromSeq1",
                   l1.to_seq            AS "toSeq1",
                   l2.route             AS "route2",
                   l2.ttn               AS "ttn2",
                   l2.dep               AS "dep2",
                   l2.arr_raw           AS "arrRaw2",
                   l2.sched             AS "sched2",
                   l2.trip              AS "trip2",
                   l2.from_seq          AS "fromSeq2",
                   l2.to_seq            AS "toSeq2",
                   CAST(EXTRACT(EPOCH FROM (l2.dep - l1.arr)) / 60 AS integer) AS "waitMinutes",
                   CAST(EXTRACT(EPOCH FROM (COALESCE(l2.arr_time, l2.dep) - l1.dep)) / 60
                        AS integer) AS "totalMinutes"
            FROM leg1 l1
            JOIN leg2 l2 ON l2.x = l1.x AND l2.day_type = l1.day_type
                        AND l2.dep >= l1.arr + (:bufferMinutes * interval '1 minute')
            JOIN stop x ON x.id = l1.x
            -- A journey nobody can be told when to leave for is not a journey.
            --
            -- The same rule the direct planner applies, and it belongs here more, not
            -- less: this list is what a rider falls through to when nothing runs straight
            -- through, so it is their whole answer. Where the timetable prints via at the
            -- boarding stop there is no departure to give, and 18 of 26 connections
            -- measured across ten stop pairs were exactly that - a change of bus at
            -- Bellville, an arrival at half past six, and no way to know when to leave
            -- home.
            WHERE l1.dep IS NOT NULL
            -- One option per departure, best first, and every departure of the day.
            --
            -- Ordering the whole lot by journey length and taking six gave six journeys
            -- that happened to be quickest, not six a rider could choose between. For
            -- KHAYELITSHA to KRAAIFONTEIN it returned 06:19, 08:49, 10:29, 13:17, 17:47 -
            -- and 06:19 twice - out of ten real departures, so somebody leaving at three
            -- in the afternoon was shown 17:47 and never told about the 15:09.
            --
            -- The screen filters these by the leave-time a rider chose, which only works
            -- if what reaches it covers the day. So the choice between two ways of making
            -- one departure is made here, on journey length, and the choice between
            -- departures is left to the person who knows when they want to leave.
            --
            -- Keyed on when the journey leaves, or when it arrives if it never says.
            --
            -- Most Golden Arrow stops are printed "via" - the bus passes and no time is
            -- published - so the first leg of a bus journey often has no departure at all,
            -- and null groups with null. Keyed on the departure alone, four ways of
            -- getting from KHAYELITSHA to WYNBERG became one: same first bus, different
            -- bus onward, arriving 17:50, 18:05 and 18:30. Those are not one journey, and
            -- the arrival is the only thing telling them apart.
            --
            -- No apostrophes in here. Spring scans the whole string for quoted ranges
            -- without stripping SQL comments, so one in a comment opens a quote that
            -- never closes and the repository fails to start.
            ORDER BY COALESCE(l1.dep, l2.arr_time), "totalMinutes" NULLS LAST,
                     "waitMinutes", l1.arr
            LIMIT :maxResults
            """, nativeQuery = true)
    List<TwoLegRow> findTwoLegConnections(@Param("fromId") Integer fromId,
                                          @Param("toId") Integer toId,
                                          @Param("bufferMinutes") int bufferMinutes,
                                          @Param("maxResults") int maxResults);

    @Query(value = """
            WITH r1 AS (
                SELECT DISTINCT b.stop_id AS id
                FROM schedule_stop a
                JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                                    AND b.stop_sequence > a.stop_sequence
                WHERE a.stop_id = :fromId
            ),
            r3 AS (
                SELECT DISTINCT a.stop_id AS id
                FROM schedule_stop a
                JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                                    AND b.stop_sequence > a.stop_sequence
                WHERE b.stop_id = :toId
            ),
            mid AS (
                SELECT DISTINCT a.stop_id AS x, b.stop_id AS y
                FROM schedule_stop a
                JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                                    AND b.stop_sequence > a.stop_sequence
                WHERE a.stop_id IN (SELECT id FROM r1)
                  AND b.stop_id IN (SELECT id FROM r3)
                  AND a.stop_id <> b.stop_id
                  AND a.stop_id <> :toId AND b.stop_id <> :fromId
            ),
            leg1 AS (
                SELECT DISTINCT ON (sc.day_type, ssb.stop_id, sc.direction_label,
                                    t1.departure_time, t2.departure_time)
                       sc.day_type, ssb.stop_id AS x, sc.direction_label AS route, tt.timetable_number AS ttn,
                       t1.departure_time AS dep, t1.raw_value AS dep_raw,
                       t2.departure_time AS arr,
                       sc.id AS sched, tr.trip_index AS trip,
                       ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
                FROM schedule_stop ssa
                JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                                      AND ssb.stop_sequence > ssa.stop_sequence
                JOIN schedule sc  ON sc.id = ssa.schedule_id
                JOIN timetable tt ON tt.id = sc.timetable_id
                JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
                JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                                 AND t1.cell_type <> 'NONE'
                JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                                 AND t2.cell_type = 'TIME'
                                 AND (t1.departure_time IS NULL
                                      OR t2.departure_time > t1.departure_time)
                WHERE ssa.stop_id = :fromId
                  AND ssb.stop_id IN (SELECT x FROM mid)
                ORDER BY sc.day_type, ssb.stop_id, sc.direction_label,
                         t1.departure_time, t2.departure_time, sc.id, tr.trip_index
            ),
            leg2 AS (
                SELECT DISTINCT ON (sc.day_type, ssa.stop_id, ssb.stop_id,
                                    sc.direction_label, t1.departure_time, t2.departure_time)
                       sc.day_type, ssa.stop_id AS x, ssb.stop_id AS y,
                       sc.direction_label AS route, tt.timetable_number AS ttn,
                       t1.departure_time AS dep, t2.departure_time AS arr,
                       sc.id AS sched, tr.trip_index AS trip,
                       ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
                -- Driven FROM mid rather than filtering with a tuple IN. The tuple
                -- form stops PostgreSQL using the stop_id index and it scans the whole
                -- self-join instead: same 31,578 rows, but 23.9s versus 1.1s.
                FROM mid m
                JOIN schedule_stop ssa ON ssa.stop_id = m.x
                JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                                      AND ssb.stop_id = m.y
                                      AND ssb.stop_sequence > ssa.stop_sequence
                JOIN schedule sc  ON sc.id = ssa.schedule_id
                JOIN timetable tt ON tt.id = sc.timetable_id
                JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
                JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                                 AND t1.cell_type = 'TIME'
                JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                                 AND t2.cell_type = 'TIME'
                                 AND t2.departure_time > t1.departure_time
                ORDER BY sc.day_type, ssa.stop_id, ssb.stop_id, sc.direction_label,
                         t1.departure_time, t2.departure_time, sc.id, tr.trip_index
            ),
            leg3 AS (
                SELECT DISTINCT ON (sc.day_type, ssa.stop_id, sc.direction_label,
                                    t1.departure_time, t2.raw_value)
                       sc.day_type, ssa.stop_id AS y, sc.direction_label AS route, tt.timetable_number AS ttn,
                       t1.departure_time AS dep, t2.raw_value AS arr_raw,
                       t2.departure_time AS arr_time,
                       sc.id AS sched, tr.trip_index AS trip,
                       ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
                FROM schedule_stop ssa
                JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                                      AND ssb.stop_sequence > ssa.stop_sequence
                JOIN schedule sc  ON sc.id = ssa.schedule_id
                JOIN timetable tt ON tt.id = sc.timetable_id
                JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
                JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                                 AND t1.cell_type = 'TIME'
                JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                                 AND t2.cell_type <> 'NONE'
                                 AND (t2.departure_time IS NULL
                                      OR t2.departure_time > t1.departure_time)
                WHERE ssb.stop_id = :toId
                  AND ssa.stop_id IN (SELECT y FROM mid)
                ORDER BY sc.day_type, ssa.stop_id, sc.direction_label,
                         t1.departure_time, t2.raw_value, sc.id, tr.trip_index
            )
            SELECT DISTINCT ON (COALESCE(l1.dep, l3.arr_time))
                   l1.day_type   AS "dayType",
                   x1.id         AS "changeId",
                   x1.name       AS "changeName",
                   x2.id         AS "change2Id",
                   x2.name       AS "change2Name",
                   l1.route      AS "route1",
                   l1.ttn        AS "ttn1",
                   l1.dep        AS "dep1",
                   l1.dep_raw    AS "depRaw1",
                   l1.arr        AS "arr1",
                   l1.sched      AS "sched1",
                   l1.trip       AS "trip1",
                   l1.from_seq   AS "fromSeq1",
                   l1.to_seq     AS "toSeq1",
                   l2.route      AS "route2",
                   l2.ttn        AS "ttn2",
                   l2.dep        AS "dep2",
                   l2.arr        AS "arr2",
                   l2.sched      AS "sched2",
                   l2.trip       AS "trip2",
                   l2.from_seq   AS "fromSeq2",
                   l2.to_seq     AS "toSeq2",
                   l3.route      AS "route3",
                   l3.ttn        AS "ttn3",
                   l3.dep        AS "dep3",
                   l3.arr_raw    AS "arrRaw3",
                   l3.sched      AS "sched3",
                   l3.trip       AS "trip3",
                   l3.from_seq   AS "fromSeq3",
                   l3.to_seq     AS "toSeq3",
                   CAST(EXTRACT(EPOCH FROM ((l2.dep - l1.arr) + (l3.dep - l2.arr))) / 60
                        AS integer) AS "waitMinutes",
                   CAST(EXTRACT(EPOCH FROM (COALESCE(l3.arr_time, l3.dep) - l1.dep)) / 60
                        AS integer) AS "totalMinutes"
            FROM leg1 l1
            JOIN leg2 l2 ON l2.x = l1.x AND l2.day_type = l1.day_type
                        AND l2.dep >= l1.arr + (:bufferMinutes * interval '1 minute')
            JOIN leg3 l3 ON l3.y = l2.y AND l3.day_type = l2.day_type
                        AND l3.dep >= l2.arr + (:bufferMinutes * interval '1 minute')
            JOIN stop x1 ON x1.id = l1.x
            JOIN stop x2 ON x2.id = l2.y
            -- A journey nobody can be told when to leave for is not a journey.
            --
            -- The same rule the direct planner applies, and it belongs here more, not
            -- less: this list is what a rider falls through to when nothing runs straight
            -- through, so it is their whole answer. Where the timetable prints via at the
            -- boarding stop there is no departure to give, and 18 of 26 connections
            -- measured across ten stop pairs were exactly that - a change of bus at
            -- Bellville, an arrival at half past six, and no way to know when to leave
            -- home.
            WHERE l1.dep IS NOT NULL
            -- One option per departure, and the whole day of them: see the two-leg query.
            -- A three-leg journey has even more ways to make the same departure, so
            -- ranking them all together and keeping a handful covered the day even less.
            ORDER BY COALESCE(l1.dep, l3.arr_time), "totalMinutes" NULLS LAST,
                     "waitMinutes", l1.arr
            LIMIT :maxResults
            """, nativeQuery = true)
    List<ThreeLegRow> findThreeLegConnections(@Param("fromId") Integer fromId,
                                              @Param("toId") Integer toId,
                                              @Param("bufferMinutes") int bufferMinutes,
                                              @Param("maxResults") int maxResults);
}
