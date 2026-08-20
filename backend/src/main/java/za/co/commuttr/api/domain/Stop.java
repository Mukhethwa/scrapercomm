package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

import java.time.OffsetDateTime;

/** Maps sql/schema.sql :: stop (a timing point). lat/lon filled by gabs_scraper.geocode. */
@Entity
@Immutable
@Table(name = "stop")
public class Stop {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "lat")
    private Double lat;

    @Column(name = "lon")
    private Double lon;

    @Column(name = "geocoded_at")
    private OffsetDateTime geocodedAt;

    @Column(name = "geocode_source")
    private String geocodeSource;

    public Integer getId() { return id; }
    public String getName() { return name; }
    public Double getLat() { return lat; }
    public Double getLon() { return lon; }
    public OffsetDateTime getGeocodedAt() { return geocodedAt; }
    public String getGeocodeSource() { return geocodeSource; }
}
