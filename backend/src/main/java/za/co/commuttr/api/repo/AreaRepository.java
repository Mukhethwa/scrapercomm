package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import za.co.commuttr.api.domain.Area;

import java.util.List;

/** The named places a rider can search, held locally. See sql/areas.sql. */
public interface AreaRepository extends JpaRepository<Area, Integer> {

    /**
     * Areas matching what has been typed so far, best first.
     *
     * <p>Prefix matching is the point. Nominatim matches whole words, so "woodst" found
     * nothing while the stop list beside it in the same menu completed the name happily -
     * two lists behaving differently with no way for a rider to tell which they were
     * typing into. This is a local LIKE, so it behaves like the stop search does.
     *
     * <p>Aliases are searched too, because OpenStreetMap and Golden Arrow both write
     * GUGULETU while the standard spelling is Gugulethu, and somebody typing their own
     * township correctly should not be told it does not exist.
     *
     * <p>Only served areas. One nothing reaches is a place, not a journey, and offering it
     * means a rider chooses it and gets an empty screen.
     */
    @Query(value = """
            SELECT * FROM area a
            WHERE a.served
              AND (lower(a.name) LIKE :contains OR a.aliases LIKE :contains)
            ORDER BY
                (lower(a.name) = :exact) DESC,
                (lower(a.name) LIKE :prefix) DESC,
                length(a.name),
                a.name
            LIMIT :maxRows
            """, nativeQuery = true)
    List<Area> search(@Param("contains") String contains,
                      @Param("prefix") String prefix,
                      @Param("exact") String exact,
                      @Param("maxRows") int maxRows);
}
