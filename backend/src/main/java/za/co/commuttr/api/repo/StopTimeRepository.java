package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.StopTime;
import za.co.commuttr.api.repo.projection.Projections.CellRow;
import za.co.commuttr.api.repo.projection.Projections.DirectServiceRow;
import za.co.commuttr.api.repo.projection.Projections.DownstreamStopRow;
import za.co.commuttr.api.repo.projection.Projections.JourneyConnRow;
import za.co.commuttr.api.repo.projection.Projections.JourneyDepartureRow;
import za.co.commuttr.api.repo.projection.Projections.PinAnchorRow;
import za.co.commuttr.api.repo.projection.Projections.ReachableRow;
import za.co.commuttr.api.repo.projection.Projections.StopAnchorRow;
import za.co.commuttr.api.repo.projection.Projections.TripStopRow;

import java.util.List;

/**
 * Everything that reads the timetable grid. The SQL is carried over verbatim from
 * gabs_scraper/api.py and gabs_scraper/planner.py so results stay byte-identical.
 */
@Repository
public interface StopTimeRepository extends JpaRepository<StopTime, Integer> {

    /** GET /api/timetables/{id} -> schedules[].trips[].cells[]. */
    @Query(value = """
            SELECT t.trip_index      AS "tripIndex",
                   ss.stop_sequence  AS "stopSequence",
                   st.cell_type      AS "cellType",
                   st.departure_time AS "departureTime",
                   st.note_code      AS "noteCode",
                   st.raw_value      AS "rawValue"
            FROM stop_time st
            JOIN trip t           ON t.id = st.trip_id
            JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
            WHERE t.schedule_id = :scheduleId
            ORDER BY t.trip_index, ss.stop_sequence
            """, nativeQuery = true)
    List<CellRow> findCellsForSchedule(@Param("scheduleId") Integer scheduleId);

    /** GET /api/stops/{id}/reachable: stops reachable on a SINGLE bus, in order. */
    @Query(value = """
            SELECT s2.id                 AS "id",
                   s2.name               AS "name",
                   s2.lat                AS "lat",
                   s2.lon                AS "lon",
                   count(*)              AS "tripCount",
                   count(DISTINCT r.id)  AS "routeCount"
            FROM schedule_stop ssx
            JOIN stop_time bx       ON bx.schedule_stop_id = ssx.id AND bx.cell_type <> 'NONE'
            JOIN stop_time byy      ON byy.trip_id = bx.trip_id AND byy.cell_type <> 'NONE'
            JOIN schedule_stop ssy  ON ssy.id = byy.schedule_stop_id
                                   AND ssy.stop_sequence > ssx.stop_sequence
            JOIN stop s2            ON s2.id = ssy.stop_id
            JOIN schedule sc        ON sc.id = ssx.schedule_id
            JOIN timetable t        ON t.id = sc.timetable_id
            JOIN route r            ON r.id = t.route_id
            WHERE ssx.stop_id = :stopId AND s2.id <> :stopId
            GROUP BY s2.id, s2.name, s2.lat, s2.lon
            ORDER BY s2.name
            """, nativeQuery = true)
    List<ReachableRow> findReachableFromStop(@Param("stopId") Integer stopId);

    /** GET /api/journeys: schedules where some trip serves both stops, in order. */
    @Query(value = """
            SELECT sc.id               AS "scheduleId",
                   sc.direction_label  AS "directionLabel",
                   sc.day_type         AS "dayType",
                   sc.day_label        AS "dayLabel",
                   r.id                AS "routeId",
                   r.name              AS "routeName",
                   t.id                AS "timetableId",
                   t.timetable_number  AS "timetableNumber",
                   ssx.id              AS "ssx",
                   ssy.id              AS "ssy",
                   ssx.stop_sequence   AS "bseq",
                   ssy.stop_sequence   AS "aseq"
            FROM schedule_stop ssx
            JOIN schedule_stop ssy ON ssy.schedule_id = ssx.schedule_id
                                  AND ssy.stop_sequence > ssx.stop_sequence
            JOIN schedule sc       ON sc.id = ssx.schedule_id
            JOIN timetable t       ON t.id = sc.timetable_id
            JOIN route r           ON r.id = t.route_id
            WHERE ssx.stop_id = :fromStopId AND ssy.stop_id = :toStopId
              AND EXISTS (
                SELECT 1 FROM stop_time bx
                JOIN stop_time byy ON byy.trip_id = bx.trip_id
                WHERE bx.schedule_stop_id = ssx.id AND byy.schedule_stop_id = ssy.id
                  AND bx.cell_type <> 'NONE' AND byy.cell_type <> 'NONE'
              )
            """, nativeQuery = true)
    List<JourneyConnRow> findConnectingSchedules(@Param("fromStopId") Integer fromStopId,
                                                 @Param("toStopId") Integer toStopId);

    /** GET /api/journeys: the board/alight pairs on one connecting schedule. */
    @Query(value = """
            SELECT bx.departure_time  AS "boardTime",
                   bx.raw_value       AS "boardRaw",
                   bx.cell_type       AS "boardType",
                   bx.note_code       AS "noteCode",
                   byy.departure_time AS "arriveTime",
                   byy.raw_value      AS "arriveRaw",
                   byy.cell_type      AS "arriveType"
            FROM trip tr
            JOIN stop_time bx  ON bx.trip_id = tr.id AND bx.schedule_stop_id = :boardScheduleStopId
            JOIN stop_time byy ON byy.trip_id = tr.id AND byy.schedule_stop_id = :alightScheduleStopId
            WHERE tr.schedule_id = :scheduleId
              AND bx.cell_type <> 'NONE' AND byy.cell_type <> 'NONE'
            """, nativeQuery = true)
    List<JourneyDepartureRow> findDepartures(@Param("boardScheduleStopId") Integer boardScheduleStopId,
                                             @Param("alightScheduleStopId") Integer alightScheduleStopId,
                                             @Param("scheduleId") Integer scheduleId);

    /** GET /api/trip_stops: what one specific trip actually serves between two positions. */
    @Query(value = """
            SELECT s.name            AS "name",
                   s.lat             AS "lat",
                   s.lon             AS "lon",
                   ss.stop_sequence  AS "stopSequence",
                   st.raw_value      AS "rawValue",
                   st.cell_type      AS "cellType",
                   st.departure_time AS "departureTime"
            FROM stop_time st
            JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
            JOIN stop s           ON s.id  = ss.stop_id
            JOIN trip tr          ON tr.id = st.trip_id
            WHERE tr.schedule_id = :scheduleId AND tr.trip_index = :tripIndex
              AND ss.stop_sequence >= :fromSeq AND ss.stop_sequence <= :toSeq
              AND st.cell_type <> 'NONE'
            ORDER BY ss.stop_sequence
            """, nativeQuery = true)
    List<TripStopRow> findTripStops(@Param("scheduleId") Integer scheduleId,
                                    @Param("tripIndex") Integer tripIndex,
                                    @Param("fromSeq") Integer fromSeq,
                                    @Param("toSeq") Integer toSeq);

    /** Planner: every (schedule, trip) anchor of a named stop. */
    @Query(value = """
            SELECT ss.schedule_id     AS "scheduleId",
                   tr.trip_index      AS "tripIndex",
                   ss.stop_sequence   AS "stopSequence",
                   st.departure_time  AS "departureTime",
                   st.raw_value       AS "rawValue",
                   s.name             AS "name"
            FROM schedule_stop ss
            JOIN stop s        ON s.id = ss.stop_id
            JOIN stop_time st  ON st.schedule_stop_id = ss.id AND st.cell_type <> 'NONE'
            JOIN trip tr       ON tr.id = st.trip_id
            WHERE ss.stop_id = :stopId
            """, nativeQuery = true)
    List<StopAnchorRow> findStopAnchors(@Param("stopId") Integer stopId);

    /**
     * Planner: anchors for a pin, expressed as the consecutive leg A -> B whose road
     * path passes near it. The caller interpolates the time between timeA and timeB.
     */
    @Query(value = """
            SELECT ssA.schedule_id     AS "scheduleId",
                   tr.trip_index       AS "tripIndex",
                   ssA.stop_sequence   AS "stopSequence",
                   sta.departure_time  AS "timeA",
                   stb.departure_time  AS "timeB",
                   sa.name             AS "nameA",
                   sb.name             AS "nameB"
            FROM schedule_stop ssA
            JOIN schedule_stop ssB ON ssB.schedule_id = ssA.schedule_id
                                  AND ssB.stop_sequence = ssA.stop_sequence + 1
                                  AND ssB.stop_id = :toStopId
            JOIN stop sa ON sa.id = ssA.stop_id
            JOIN stop sb ON sb.id = ssB.stop_id
            JOIN trip tr ON tr.schedule_id = ssA.schedule_id
            JOIN stop_time sta ON sta.trip_id = tr.id AND sta.schedule_stop_id = ssA.id
                              AND sta.cell_type <> 'NONE'
            JOIN stop_time stb ON stb.trip_id = tr.id AND stb.schedule_stop_id = ssB.id
                              AND stb.cell_type <> 'NONE'
            WHERE ssA.stop_id = :fromStopId
            """, nativeQuery = true)
    List<PinAnchorRow> findPinAnchors(@Param("toStopId") Integer toStopId,
                                      @Param("fromStopId") Integer fromStopId);

    /** Planner: distinct stops a given trip serves after a fractional position. */
    @Query(value = """
            SELECT s.id   AS "id",
                   s.name AS "name",
                   s.lat  AS "lat",
                   s.lon  AS "lon"
            FROM stop_time st
            JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
            JOIN stop s           ON s.id = ss.stop_id
            JOIN trip tr          ON tr.id = st.trip_id
            WHERE tr.schedule_id = :scheduleId AND tr.trip_index = :tripIndex
              AND st.cell_type <> 'NONE' AND ss.stop_sequence > :afterPosition
            """, nativeQuery = true)
    List<DownstreamStopRow> findDownstreamStops(@Param("scheduleId") Integer scheduleId,
                                                @Param("tripIndex") Integer tripIndex,
                                                @Param("afterPosition") double afterPosition);

    /**
     * GET /api/reachable_point, in one statement.
     *
     * <p>Previously the caller resolved the pin to anchors in Java and then asked, per
     * anchor, what lay downstream — and a Cape Town CBD pin matches ~185 legs which
     * resolve to ~61,000 (schedule, trip) anchors, so the endpoint fired ~61,000 tiny
     * queries and took 30-50 seconds.
     *
     * <p>The anchors are derivable from the legs, and there are only ~185 of those, so
     * the legs arrive as one JSON parameter and the database derives the anchors and
     * walks downstream itself. Leg matching stays in Java because the distance-to-
     * polyline maths lives there.
     */
    @Query(value = """
            WITH legs AS (
                SELECT * FROM jsonb_to_recordset(CAST(:legsJson AS jsonb))
                    AS x(a integer, b integer, f double precision)
            ),
            anchors AS (
                SELECT ssa.schedule_id AS schedule_id,
                       tr.trip_index   AS trip_index,
                       min(ssa.stop_sequence + l.f) AS pos
                FROM legs l
                JOIN schedule_stop ssa ON ssa.stop_id = l.a
                JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                                      AND ssb.stop_sequence = ssa.stop_sequence + 1
                                      AND ssb.stop_id = l.b
                JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
                JOIN stop_time sa ON sa.trip_id = tr.id AND sa.schedule_stop_id = ssa.id
                                 AND sa.cell_type <> 'NONE'
                JOIN stop_time sb ON sb.trip_id = tr.id AND sb.schedule_stop_id = ssb.id
                                 AND sb.cell_type <> 'NONE'
                GROUP BY ssa.schedule_id, tr.trip_index
            )
            SELECT s.id       AS "id",
                   s.name     AS "name",
                   s.lat      AS "lat",
                   s.lon      AS "lon",
                   count(*)   AS "tripCount"
            FROM anchors a
            JOIN trip tr          ON tr.schedule_id = a.schedule_id
                                 AND tr.trip_index = a.trip_index
            JOIN stop_time st     ON st.trip_id = tr.id AND st.cell_type <> 'NONE'
            JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
                                 AND ss.stop_sequence > a.pos
            JOIN stop s           ON s.id = ss.stop_id
            GROUP BY s.id, s.name, s.lat, s.lon
            ORDER BY s.name
            """, nativeQuery = true)
    List<ReachableRow> findReachableFromLegs(@Param("legsJson") String legsJson);

    /** GET /api/nearby_origins: does this candidate stop have a direct bus to the target? */
    @Query(value = """
            SELECT min(b.departure_time) AS "earliest", count(*) AS "tripCount"
            FROM schedule_stop ss1
            JOIN schedule_stop ss2 ON ss2.schedule_id = ss1.schedule_id
                                  AND ss2.stop_sequence > ss1.stop_sequence
            JOIN schedule sc ON sc.id = ss1.schedule_id
            JOIN trip tr     ON tr.schedule_id = ss1.schedule_id
            JOIN stop_time b ON b.trip_id = tr.id AND b.schedule_stop_id = ss1.id
                            AND b.cell_type <> 'NONE'
            JOIN stop_time a ON a.trip_id = tr.id AND a.schedule_stop_id = ss2.id
                            AND a.cell_type <> 'NONE'
            WHERE ss1.stop_id = :fromStopId AND ss2.stop_id = :toStopId
              AND (CAST(:dayType AS text) IS NULL OR sc.day_type = CAST(:dayType AS text))
            """, nativeQuery = true)
    DirectServiceRow findDirectService(@Param("fromStopId") Integer fromStopId,
                                       @Param("toStopId") Integer toStopId,
                                       @Param("dayType") String dayType);
}
