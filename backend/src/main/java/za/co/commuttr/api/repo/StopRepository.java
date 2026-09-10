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

    /**
     * Stops of one kind within a straight-line distance of a point, nearest first.
     *
     * For planning from a place rather than a stop. A bus is found by the road it drives
     * down, which is what leg_geometry is for; a train is not, and a rider does not board
     * one between stations. They walk to the station - so a place near a station reaches
     * the trains that call there, and how far they walk is the whole of the story.
     *
     * <p>Nearest is not the same as useful, and taking only the four nearest threw away
     * the answer. Twenty-seven bus stops stand within walking distance of a pin dropped in
     * the Cape Town CBD, and CAPE TOWN - the terminus 219 routes run to - is the tenth of
     * them. The four that beat it are KEEROM STR, BUITENSINGEL STR, SWINDEN - LOOP STR and
     * LOOP STR. So a rider asking for Kraaifontein to Cape Town was told the train was the
     * only way, not because no bus runs it, but because the stop every bus runs to was
     * five hundred metres too far down a list that stopped at four.
     *
     * <p>So the walking radius decides who is eligible, and then two questions decide who
     * is asked: which stops are closest, and which are served most. A rider will walk past
     * a kerb with one route on it to reach the terminus nine hundred metres away, and both
     * kinds of answer belong in the list.
     *
     * <p>It stays a bounded number rather than everything inside the radius, because the
     * anchors of a busy stop are tens of thousands of rows - CAPE TOWN alone is about
     * 38,000 - and taking all twenty-seven took a CBD search from two seconds to eleven.
     */
    @Query(value = """
            WITH within AS (
                SELECT s.id, s.name, s.lat, s.lon, o.code, o.kind,
                       6371000 * acos(least(1,
                           cos(radians(s.lat)) * cos(radians(CAST(:lat AS double precision)))
                             * cos(radians(CAST(:lon AS double precision)) - radians(s.lon))
                         + sin(radians(s.lat))
                             * sin(radians(CAST(:lat AS double precision))))) AS away,
                       (SELECT count(*) FROM schedule_stop ss WHERE ss.stop_id = s.id) AS calls
                FROM stop s
                JOIN operator o ON o.id = s.operator_id AND o.kind = :kind
                WHERE s.lat IS NOT NULL
            ),
            eligible AS (
                SELECT * FROM within WHERE away <= CAST(:withinM AS double precision)
            ),
            chosen AS (
                (SELECT id FROM eligible ORDER BY away LIMIT 6)
                UNION
                (SELECT id FROM eligible ORDER BY calls DESC, away LIMIT 4)
            )
            SELECT e.id AS "id", e.name AS "name", e.lat AS "lat", e.lon AS "lon",
                   e.code AS "operatorCode", e.kind AS "operatorKind"
            FROM eligible e JOIN chosen c ON c.id = e.id
            ORDER BY e.away
            """, nativeQuery = true)
    List<StopRow> findNearestOfKind(@Param("lat") double lat,
                                    @Param("lon") double lon,
                                    @Param("kind") String kind,
                                    @Param("withinM") double withinM);

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
                   transfers, basis, basis_from, basis_to, zone_approx,
                   -- What a cash passenger pays, for the 21 routes Golden Arrow prints a
                   -- cash fare for. Null everywhere else, because it is published nowhere
                   -- else and cannot be worked out from the card price.
                   cash_cents, CAST(cash_effective_from AS text),
                   -- Metrorail sells a journey four ways and prices it by distance band,
                   -- so unlike Golden Arrow these are real tickets a rider chooses
                   -- between. See prasa_scraper.fares.
                   return_cents, weekly_sat_cents, distance_km
            FROM journey_fare
            WHERE from_stop_id = :fromId AND to_stop_id = :toId
            """, nativeQuery = true)
    List<Object[]> findJourneyFare(@Param("fromId") Integer fromId,
                                   @Param("toId") Integer toId);
}
