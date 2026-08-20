package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;

/**
 * Maps sql/schema.sql :: leg_geometry, the real road path between two consecutive
 * timing points (populated by gabs_scraper.geometry). {@code path} is JSONB holding
 * a list of [lat, lon] pairs; it is kept as the raw JSON text and parsed on demand.
 */
@Entity
@Immutable
@Table(name = "leg_geometry")
@IdClass(LegGeometryId.class)
public class LegGeometry {

    @Id
    @Column(name = "from_stop_id")
    private Integer fromStopId;

    @Id
    @Column(name = "to_stop_id")
    private Integer toStopId;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "path")
    private String path;

    @Column(name = "length_m")
    private Double lengthM;

    @Column(name = "min_lat")
    private Double minLat;

    @Column(name = "min_lon")
    private Double minLon;

    @Column(name = "max_lat")
    private Double maxLat;

    @Column(name = "max_lon")
    private Double maxLon;

    @Column(name = "source")
    private String source;

    @Column(name = "fetched_at")
    private OffsetDateTime fetchedAt;

    public Integer getFromStopId() { return fromStopId; }
    public Integer getToStopId() { return toStopId; }
    public String getPath() { return path; }
    public Double getLengthM() { return lengthM; }
    public Double getMinLat() { return minLat; }
    public Double getMinLon() { return minLon; }
    public Double getMaxLat() { return maxLat; }
    public Double getMaxLon() { return maxLon; }
    public String getSource() { return source; }
    public OffsetDateTime getFetchedAt() { return fetchedAt; }
}
