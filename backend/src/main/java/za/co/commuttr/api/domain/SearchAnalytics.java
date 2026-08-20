package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.OffsetDateTime;

/**
 * Maps sql/analytics.sql :: search_analytics.
 *
 * <p>The only table this service writes. It is purely additive, so no scraper-owned
 * table is modified. Rows are inserted off the request thread by
 * {@link za.co.commuttr.api.analytics.SearchAnalyticsListener}.
 */
@Entity
@Table(name = "search_analytics")
public class SearchAnalytics {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(name = "endpoint", nullable = false)
    private String endpoint;

    @Column(name = "from_kind")
    private String fromKind;

    @Column(name = "from_stop_id")
    private Integer fromStopId;

    @Column(name = "from_lat")
    private Double fromLat;

    @Column(name = "from_lon")
    private Double fromLon;

    @Column(name = "to_kind")
    private String toKind;

    @Column(name = "to_stop_id")
    private Integer toStopId;

    @Column(name = "to_lat")
    private Double toLat;

    @Column(name = "to_lon")
    private Double toLon;

    @Column(name = "option_count", nullable = false)
    private int optionCount;

    @Column(name = "duration_ms")
    private Long durationMs;

    @Column(name = "searched_at", nullable = false)
    private OffsetDateTime searchedAt;

    protected SearchAnalytics() { }

    public SearchAnalytics(String endpoint,
                           String fromKind, Integer fromStopId, Double fromLat, Double fromLon,
                           String toKind, Integer toStopId, Double toLat, Double toLon,
                           int optionCount, Long durationMs, OffsetDateTime searchedAt) {
        this.endpoint = endpoint;
        this.fromKind = fromKind;
        this.fromStopId = fromStopId;
        this.fromLat = fromLat;
        this.fromLon = fromLon;
        this.toKind = toKind;
        this.toStopId = toStopId;
        this.toLat = toLat;
        this.toLon = toLon;
        this.optionCount = optionCount;
        this.durationMs = durationMs;
        this.searchedAt = searchedAt;
    }

    public Long getId() { return id; }
    public String getEndpoint() { return endpoint; }
    public int getOptionCount() { return optionCount; }
    public OffsetDateTime getSearchedAt() { return searchedAt; }
}
