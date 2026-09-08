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
     * Which of those areas also have a station in them.
     *
     * An area is a name GABS uses for a part of the city, and by construction it is a name
     * no stop carries - that is the rule that makes it an area rather than a stop. So no
     * area is ever a train terminus and no name match can answer this. Only geography can:
     * an area has trains if a Metrorail station stands among the bus stops that make it up.
     *
     * A kilometre and a half, which is the distance somebody would walk to a train rather
     * than wait for a second bus. Areas whose stops have no coordinates simply do not
     * appear here - the claim is only made where it can be shown, because telling a rider
     * there is a train in Bluedowns when there is not sends them to look for a station.
     */
    @Query(value = """
            WITH endpoints AS (
              SELECT DISTINCT origin AS area FROM route WHERE origin <> ''
              UNION SELECT DISTINCT destination FROM route WHERE destination <> ''
            ),
            areas AS (
              SELECT e.area FROM endpoints e
              LEFT JOIN stop s ON s.name = e.area
              WHERE s.id IS NULL
            ),
            here AS (
              SELECT a.area, s.lat, s.lon
              FROM areas a
              JOIN stop s   ON s.lat IS NOT NULL AND s.name ILIKE '%' || a.area || '%'
              JOIN operator o ON o.id = s.operator_id AND o.kind = 'bus'
            )
            SELECT DISTINCT h.area
            FROM here h
            JOIN stop t     ON t.lat IS NOT NULL
            JOIN operator o ON o.id = t.operator_id AND o.kind = 'train'
            WHERE 6371 * acos(least(1,
                    cos(radians(h.lat)) * cos(radians(t.lat))
                      * cos(radians(t.lon) - radians(h.lon))
                  + sin(radians(h.lat)) * sin(radians(t.lat)))) <= 1.5
            ORDER BY h.area
            """, nativeQuery = true)
    List<String> findAreasWithRail();

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
