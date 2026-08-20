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
            SELECT id AS "id", name AS "name", lat AS "lat", lon AS "lon"
            FROM stop WHERE id = :stopId
            """, nativeQuery = true)
    Optional<StopRow> findRowById(@Param("stopId") Integer stopId);

    @Query(value = """
            SELECT id AS "id", name AS "name", lat AS "lat", lon AS "lon"
            FROM stop WHERE id IN (:stopIds)
            """, nativeQuery = true)
    List<StopRow> findRowsByIds(@Param("stopIds") Collection<Integer> stopIds);

    /**
     * GET /api/stops?q=. Prefix matches float to the top, then alphabetical, exactly
     * as {@code ORDER BY (name ILIKE 'q%') DESC, name} did in FastAPI.
     */
    @Query(value = """
            SELECT id AS "id", name AS "name", lat AS "lat", lon AS "lon"
            FROM stop
            WHERE name ILIKE :contains
            ORDER BY (name ILIKE :prefix) DESC, name
            LIMIT :maxRows
            """, nativeQuery = true)
    List<StopRow> searchByName(@Param("contains") String contains,
                               @Param("prefix") String prefix,
                               @Param("maxRows") int maxRows);

    @Query(value = """
            SELECT id AS "id", name AS "name", lat AS "lat", lon AS "lon"
            FROM stop ORDER BY name LIMIT :maxRows
            """, nativeQuery = true)
    List<StopRow> listAll(@Param("maxRows") int maxRows);

    /** Bounding-box pre-filter for GET /api/nearby_origins (refined by haversine). */
    @Query(value = """
            SELECT id AS "id", name AS "name", lat AS "lat", lon AS "lon"
            FROM stop
            WHERE lat IS NOT NULL
              AND lat BETWEEN :minLat AND :maxLat
              AND lon BETWEEN :minLon AND :maxLon
              AND id <> :toStopId
              AND id <> COALESCE(CAST(:excludeStopId AS integer), -1)
            """, nativeQuery = true)
    List<StopRow> findInBoundingBox(@Param("minLat") double minLat,
                                    @Param("maxLat") double maxLat,
                                    @Param("minLon") double minLon,
                                    @Param("maxLon") double maxLon,
                                    @Param("toStopId") Integer toStopId,
                                    @Param("excludeStopId") Integer excludeStopId);

    /** Straight-line fallback when a leg has no cached road geometry. */
    @Query(value = """
            SELECT id AS "id", name AS "name", lat AS "lat", lon AS "lon"
            FROM stop WHERE id IN (:a, :b)
            """, nativeQuery = true)
    List<StopRow> findPair(@Param("a") Integer a, @Param("b") Integer b);
}
