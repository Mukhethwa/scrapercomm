package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.Schedule;
import za.co.commuttr.api.repo.projection.Projections.ScheduleMetaRow;

import java.util.Collection;
import java.util.List;

@Repository
public interface ScheduleRepository extends JpaRepository<Schedule, Integer> {

    /**
     * GET /api/timetables/{id} -> schedules[], ordered page, direction, then day type
     * in commuter order (weekday, Saturday, Sunday, public holiday, anything else).
     */
    @Query("""
            SELECT s FROM Schedule s
            WHERE s.timetableId = :timetableId
            ORDER BY s.pageNumber, s.directionIndex,
                     CASE s.dayType
                        WHEN 'WEEKDAY' THEN 0
                        WHEN 'SATURDAY' THEN 1
                        WHEN 'SUNDAY' THEN 2
                        WHEN 'PUBLIC_HOLIDAY' THEN 3
                        ELSE 4
                     END
            """)
    List<Schedule> findForTimetable(@Param("timetableId") Integer timetableId);

    /** Planner grouping metadata for a batch of schedules. */
    @Query(value = """
            SELECT sc.id              AS "id",
                   sc.direction_label AS "directionLabel",
                   sc.day_type        AS "dayType",
                   sc.day_label       AS "dayLabel",
                   t.timetable_number AS "timetableNumber"
            FROM schedule sc
            JOIN timetable t ON t.id = sc.timetable_id
            WHERE sc.id IN (:scheduleIds)
            """, nativeQuery = true)
    List<ScheduleMetaRow> findMeta(@Param("scheduleIds") Collection<Integer> scheduleIds);
}
