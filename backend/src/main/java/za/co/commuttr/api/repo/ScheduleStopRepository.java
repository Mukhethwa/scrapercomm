package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.ScheduleStop;
import za.co.commuttr.api.repo.projection.Projections.ScheduleStopRow;
import za.co.commuttr.api.repo.projection.Projections.SegmentStopRow;
import za.co.commuttr.api.repo.projection.Projections.SegmentStopWithIdRow;

import java.util.List;

@Repository
public interface ScheduleStopRepository extends JpaRepository<ScheduleStop, Integer> {

    /** GET /api/timetables/{id} -> schedules[].stops[]. */
    @Query(value = """
            SELECT ss.stop_sequence AS "stopSequence",
                   s.name           AS "name",
                   s.lat            AS "lat",
                   s.lon            AS "lon"
            FROM schedule_stop ss
            JOIN stop s ON s.id = ss.stop_id
            WHERE ss.schedule_id = :scheduleId
            ORDER BY ss.stop_sequence
            """, nativeQuery = true)
    List<ScheduleStopRow> findStopsForSchedule(@Param("scheduleId") Integer scheduleId);

    /** GET /api/journeys -> options[].segment_stops[] (board..alight inclusive). */
    @Query(value = """
            SELECT s.name           AS "name",
                   s.lat            AS "lat",
                   s.lon            AS "lon",
                   ss.stop_sequence AS "stopSequence"
            FROM schedule_stop ss
            JOIN stop s ON s.id = ss.stop_id
            WHERE ss.schedule_id = :scheduleId
              AND ss.stop_sequence BETWEEN :fromSeq AND :toSeq
            ORDER BY ss.stop_sequence
            """, nativeQuery = true)
    List<SegmentStopRow> findSegment(@Param("scheduleId") Integer scheduleId,
                                     @Param("fromSeq") Integer fromSeq,
                                     @Param("toSeq") Integer toSeq);

    /** GET /api/plan -> options[].segment_stops[]; ids are needed to stitch road geometry. */
    @Query(value = """
            SELECT s.id             AS "stopId",
                   s.name           AS "name",
                   s.lat            AS "lat",
                   s.lon            AS "lon",
                   ss.stop_sequence AS "stopSequence"
            FROM schedule_stop ss
            JOIN stop s ON s.id = ss.stop_id
            WHERE ss.schedule_id = :scheduleId
              AND ss.stop_sequence >= :fromSeq
              AND ss.stop_sequence <= :toSeq
            ORDER BY ss.stop_sequence
            """, nativeQuery = true)
    List<SegmentStopWithIdRow> findSegmentWithIds(@Param("scheduleId") Integer scheduleId,
                                                  @Param("fromSeq") Integer fromSeq,
                                                  @Param("toSeq") Integer toSeq);
}
