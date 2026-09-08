package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.Stop;
import za.co.commuttr.api.repo.projection.Projections.StopRow;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface StopRepository extends JpaRepository<Stop, Integer> {

    @Query(value = """
            SELECT s.id AS "id", s.name AS "name", s.lat AS "lat", s.lon AS "lon",
                   o.code AS "operatorCode", o.kind AS "operatorKind"
            FROM stop s LEFT JOIN operator o ON o.id = s.operator_id WHERE s.id = :stopId
            """, nativeQuery = true)
    Optional<StopRow> findRowById(@Param("stopId") Integer stopId);

    @Query(value = """
            SELECT s.id AS "id", s.name AS "name", s.lat AS "lat", s.lon AS "lon",
                   o.code AS "operatorCode", o.kind AS "operatorKind"
            FROM stop s LEFT JOIN operator o ON o.id = s.operator_id WHERE s.id IN (:stopIds)
            """, nativeQuery = true)
    List<StopRow> findRowsByIds(@Param("stopIds") Collection<Integer> stopIds);

    /**
     * GET /api/stops?q=. Prefix matches float to the top, then alphabetical, exactly
     * as {@code ORDER BY (name ILIKE 'q%') DESC, name} did in FastAPI.
     *
     * The second clause matches ignoring spaces. The timetables and the riders disagree
     * about whether a name is one word or two - BLUE DOWNS against "bluedowns", CAPE
     * TOWN against "capetown" - and a search that cannot cross a space returns nothing
     * for a stop that plainly exists.
     */
    @Query(value = """
            SELECT s.id AS "id", s.name AS "name", s.lat AS "lat", s.lon AS "lon",
                   o.code AS "operatorCode", o.kind AS "operatorKind"
            FROM stop s
            LEFT JOIN operator o ON o.id = s.operator_id
            WHERE s.name ILIKE :contains OR replace(s.name, ' ', '') ILIKE :squashed
            ORDER BY (s.name ILIKE :prefix) DESC, s.name
            LIMIT :maxRows
            """, nativeQuery = true)
    List<StopRow> searchByName(@Param("contains") String contains,
                               @Param("squashed") String squashed,
                               @Param("prefix") String prefix,
                               @Param("maxRows") int maxRows);

    @Query(value = """
            SELECT s.id AS "id", s.name AS "name", s.lat AS "lat", s.lon AS "lon",
                   o.code AS "operatorCode", o.kind AS "operatorKind"
            FROM stop s LEFT JOIN operator o ON o.id = s.operator_id
            ORDER BY s.name LIMIT :maxRows
            """, nativeQuery = true)
    List<StopRow> listAll(@Param("maxRows") int maxRows);

    /** Bounding-box pre-filter for GET /api/nearby_origins (refined by haversine). */
    @Query(value = """
            SELECT s.id AS "id", s.name AS "name", s.lat AS "lat", s.lon AS "lon",
                   o.code AS "operatorCode", o.kind AS "operatorKind"
            FROM stop s
            LEFT JOIN operator o ON o.id = s.operator_id
            WHERE s.lat IS NOT NULL
              AND s.lat BETWEEN :minLat AND :maxLat
              AND s.lon BETWEEN :minLon AND :maxLon
              AND s.id <> :toStopId
              AND s.id <> COALESCE(CAST(:excludeStopId AS integer), -1)
            """, nativeQuery = true)
    List<StopRow> findInBoundingBox(@Param("minLat") double minLat,
                                    @Param("maxLat") double maxLat,
                                    @Param("minLon") double minLon,
                                    @Param("maxLon") double maxLon,
                                    @Param("toStopId") Integer toStopId,
                                    @Param("excludeStopId") Integer excludeStopId);

    /** Straight-line fallback when a leg has no cached road geometry. */
    @Query(value = """
            SELECT s.id AS "id", s.name AS "name", s.lat AS "lat", s.lon AS "lon",
                   o.code AS "operatorCode", o.kind AS "operatorKind"
            FROM stop s LEFT JOIN operator o ON o.id = s.operator_id WHERE s.id IN (:a, :b)
            """, nativeQuery = true)
    List<StopRow> findPair(@Param("a") Integer a, @Param("b") Integer b);

    /**
     * The published fare for riding between two stops, or nothing.
     *
     * Resolved ahead of time by {@code gabs_scraper.pricing} - which zone a stop sits
     * in, and which of three published fares covers the ride - so both services read
     * the same numbers instead of each reimplementing that and drifting apart.
     */
    @Query(value = """
            SELECT code, per_ride_cents, five_ride_cents, weekly_cents, monthly_cents,
                   transfers, basis, basis_from, basis_to, zone_approx
            FROM journey_fare
            WHERE from_stop_id = :fromId AND to_stop_id = :toId
            """, nativeQuery = true)
    List<Object[]> findJourneyFare(@Param("fromId") Integer fromId,
                                   @Param("toId") Integer toId);
}
