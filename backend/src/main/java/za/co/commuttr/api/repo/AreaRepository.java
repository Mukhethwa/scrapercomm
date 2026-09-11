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
     * <p>One row per name. OpenStreetMap maps Atlantis as a node and again as an outline,
     * and two identical suggestions is a choice with no difference behind it - the same
     * reasoning that collapsed Parow when it was mapped as a town and a suburb.
     *
     * <p>Only served areas, and only by the network the rider has chosen. One nothing
     * reaches is a place, not a journey; and offering Hout Bay under a Metro Rail filter,
     * when the nearest station is forty kilometres away, is the same failure wearing a
     * different hat - suggested, chosen, and answered with nothing. 873 of the 884 places
     * are reachable by bus and 584 by train, so the filter is not cosmetic.
     */
    @Query(value = """
            SELECT * FROM (
                -- One row per name, chosen inside. DISTINCT ON has to be ordered by the
                -- thing it distinguishes, which is not the order a rider should read, so
                -- the ranking happens outside where it is free to.
                SELECT DISTINCT ON (
                    -- One row per place, judged with the punctuation out. Keyed on
                    -- lower(name) this kept Fir Grove beside Firgrove beside FIRGROVE,
                    -- and Smartie Town beside Smartietown: one place, listed two or
                    -- three times, with nothing to choose between the lines. A space is
                    -- not a different place.
                    replace(replace(replace(replace(lower(a.name), ' ', ''),
                                            chr(39), ''), '.', ''), '-', '')
                ) a.*
                FROM area a
                WHERE (CASE WHEN :kind = 'bus'   THEN a.served_bus
                            WHEN :kind = 'train' THEN a.served_train
                            ELSE a.served END)
                  AND (lower(a.name) LIKE :contains OR a.aliases LIKE :contains)
                -- A mapped place beats one built from a stop of the same name. Entries
                -- built from stops exist to fill the gaps OpenStreetMap leaves - BUH REIN
                -- and four hundred others - and where OSM does have the place, its own
                -- centre is what somebody typing the name means. This was a.kind, which
                -- ranked the stop kind ahead of suburb and town by the alphabet alone, so
                -- "bellville" started answering with the station rather than the town.
                ORDER BY replace(replace(replace(replace(lower(a.name), ' ', ''),
                                                 chr(39), ''), '.', ''), '-', ''),
                         (a.kind = 'stop'), a.id
            ) d
            ORDER BY
                (lower(d.name) = :exact) DESC,
                (lower(d.name) LIKE :prefix) DESC,
                length(d.name),
                d.name
            LIMIT :maxRows
            """, nativeQuery = true)
    List<Area> search(@Param("contains") String contains,
                      @Param("prefix") String prefix,
                      @Param("exact") String exact,
                      @Param("kind") String kind,
                      @Param("maxRows") int maxRows);
}
