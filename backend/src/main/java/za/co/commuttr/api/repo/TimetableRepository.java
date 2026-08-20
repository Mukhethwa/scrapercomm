package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.Timetable;
import za.co.commuttr.api.repo.projection.Projections.TimetableDetailRow;
import za.co.commuttr.api.repo.projection.Projections.TimetableRow;

import java.util.List;
import java.util.Optional;

@Repository
public interface TimetableRepository extends JpaRepository<Timetable, Integer> {

    /** GET /api/routes/{id} -> timetables[]. raw_text is deliberately not selected. */
    @Query(value = """
            SELECT id                AS "id",
                   timetable_number  AS "timetableNumber",
                   is_public_holiday AS "isPublicHoliday",
                   effective_from    AS "effectiveFrom",
                   effective_to      AS "effectiveTo",
                   pdf_filename      AS "pdfFilename",
                   pdf_url           AS "pdfUrl",
                   page_count        AS "pageCount",
                   parse_status      AS "parseStatus"
            FROM timetable
            WHERE route_id = :routeId
            ORDER BY is_public_holiday, timetable_number, effective_from
            """, nativeQuery = true)
    List<TimetableRow> findRowsByRouteId(@Param("routeId") Integer routeId);

    /** GET /api/timetables/{id} header (timetable joined to its route). */
    @Query(value = """
            SELECT t.id                AS "id",
                   t.timetable_number  AS "timetableNumber",
                   t.is_public_holiday AS "isPublicHoliday",
                   t.effective_from    AS "effectiveFrom",
                   t.effective_to      AS "effectiveTo",
                   t.pdf_filename      AS "pdfFilename",
                   t.pdf_url           AS "pdfUrl",
                   t.page_count        AS "pageCount",
                   r.id                AS "routeId",
                   r.name              AS "routeName"
            FROM timetable t
            JOIN route r ON r.id = t.route_id
            WHERE t.id = :timetableId
            """, nativeQuery = true)
    Optional<TimetableDetailRow> findDetailById(@Param("timetableId") Integer timetableId);
}
