package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.LegGeometry;
import za.co.commuttr.api.domain.LegGeometryId;
import za.co.commuttr.api.repo.projection.Projections.LegGeometryRow;

import java.util.List;
import java.util.Optional;

@Repository
public interface LegGeometryRepository extends JpaRepository<LegGeometry, LegGeometryId> {

    /**
     * Legs whose bounding box (widened by {@code deg}) contains the point. The caller
     * then measures the real distance to the polyline.
     *
     * <p>{@code CAST(path AS text)} rather than {@code path::text}: Hibernate would read
     * the {@code ::text} cast operator as a named parameter.
     */
    @Query(value = """
            SELECT from_stop_id       AS "fromStopId",
                   to_stop_id         AS "toStopId",
                   CAST(path AS text) AS "path",
                   length_m           AS "lengthM"
            FROM leg_geometry
            WHERE path IS NOT NULL
              AND min_lat - :deg <= :lat AND max_lat + :deg >= :lat
              AND min_lon - :deg <= :lon AND max_lon + :deg >= :lon
            """, nativeQuery = true)
    List<LegGeometryRow> findNearPoint(@Param("deg") double deg,
                                       @Param("lat") double lat,
                                       @Param("lon") double lon);

    @Query(value = """
            SELECT CAST(path AS text)
            FROM leg_geometry
            WHERE from_stop_id = :fromStopId AND to_stop_id = :toStopId
            """, nativeQuery = true)
    Optional<String> findPathJson(@Param("fromStopId") Integer fromStopId,
                                  @Param("toStopId") Integer toStopId);
}
