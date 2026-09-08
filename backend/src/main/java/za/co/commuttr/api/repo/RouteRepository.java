package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.Route;
import za.co.commuttr.api.repo.projection.Projections.RouteSummaryRow;

import java.util.List;

@Repository
public interface RouteRepository extends JpaRepository<Route, Integer> {

    /**
     * GET /api/routes. The Python version built the WHERE clause dynamically; the
     * null-guarded predicates below are equivalent and keep the query plan cacheable.
     * {@code namePattern} already carries its % wildcards.
     */
    @Query(value = """
            SELECT r.id            AS "id",
                   r.name          AS "name",
                   r.origin        AS "origin",
                   r.destination   AS "destination",
                   r.letter_group  AS "letterGroup",
                   count(t.id)     AS "timetableCount"
            FROM route r
            LEFT JOIN timetable t ON t.route_id = r.id
            WHERE (CAST(:namePattern AS text) IS NULL OR r.name ILIKE CAST(:namePattern AS text))
              AND (CAST(:letter AS text) IS NULL OR r.letter_group = CAST(:letter AS text))
            GROUP BY r.id
            ORDER BY r.name
            """, nativeQuery = true)
    List<RouteSummaryRow> search(@Param("namePattern") String namePattern,
                                 @Param("letter") String letter);

    /**
     * GET /api/areas. Route-endpoint area names that are not themselves published
     * stops, so an area can still be a first-class origin/destination in search.
     */
    @Query(value = """
            WITH endpoints AS (
              SELECT DISTINCT origin AS area FROM route WHERE origin <> ''
              UNION SELECT DISTINCT destination FROM route WHERE destination <> ''
            )
            SELECT e.area FROM endpoints e
            LEFT JOIN stop s ON s.name = e.area
            WHERE s.id IS NULL
            ORDER BY e.area
            """, nativeQuery = true)
    List<String> findAreaNames();

    /**
     * Operators with something behind them, and how much.
     *
     * Counted rather than listed, because the question the UI is asking is whether
     * pressing this chip will show a rider anything.
     */
    @Query(value = """
            SELECT o.code            AS "code",
                   o.name            AS "name",
                   o.kind            AS "kind",
                   count(DISTINCT r.id)  AS "routes",
                   count(st.id)          AS "departures"
            FROM operator o
            LEFT JOIN route r      ON r.operator_id = o.id
            LEFT JOIN timetable t  ON t.route_id = r.id
            LEFT JOIN schedule sc  ON sc.timetable_id = t.id
            LEFT JOIN trip tr      ON tr.schedule_id = sc.id
            LEFT JOIN stop_time st ON st.trip_id = tr.id
            GROUP BY o.code, o.name, o.kind
            ORDER BY o.name
            """, nativeQuery = true)
    List<Object[]> operatorTotals();
}
