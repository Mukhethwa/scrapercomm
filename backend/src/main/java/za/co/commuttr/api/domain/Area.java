package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

/**
 * Maps sql/areas.sql :: area, the named places of Cape Town held locally.
 *
 * <p>Fetched once from OpenStreetMap rather than asked of Nominatim per keystroke. See
 * {@code gabs_scraper.areas} for why, and for how {@code served} is decided.
 */
@Entity
@Immutable
@Table(name = "area")
public class Area {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "kind", nullable = false)
    private String kind;

    @Column(name = "lat", nullable = false)
    private Double lat;

    @Column(name = "lon", nullable = false)
    private Double lon;

    @Column(name = "full_name")
    private String fullName;

    @Column(name = "aliases", nullable = false)
    private String aliases;

    @Column(name = "served", nullable = false)
    private boolean served;

    public Integer getId() { return id; }
    public String getName() { return name; }
    public String getKind() { return kind; }
    public Double getLat() { return lat; }
    public Double getLon() { return lon; }
    public String getFullName() { return fullName; }
    public String getAliases() { return aliases; }
    public boolean isServed() { return served; }
}
