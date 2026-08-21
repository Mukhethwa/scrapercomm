package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * Maps sql/analytics.sql :: search_analytics_option — one row per journey option a
 * search returned.
 *
 * <p>{@link SearchAnalytics} records how many options came back; this records which, so
 * route demand can actually be measured. Without it you can only say "Bellville to
 * Nyanga was searched 400 times", never "route 004401 is the most sought-after service".
 *
 * <p>The parent link is a plain FK column rather than a {@code @ManyToOne}: rows are
 * written once and read by SQL, so an association would buy nothing.
 */
@Entity
@Table(name = "search_analytics_option")
public class SearchAnalyticsOption {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id")
    private Long id;

    @Column(name = "search_id", nullable = false)
    private Long searchId;

    @Column(name = "timetable_number")
    private String timetableNumber;

    @Column(name = "route_label")
    private String routeLabel;

    @Column(name = "day_type")
    private String dayType;

    @Column(name = "departure_count", nullable = false)
    private int departureCount;

    protected SearchAnalyticsOption() { }

    public SearchAnalyticsOption(Long searchId, String timetableNumber, String routeLabel,
                                 String dayType, int departureCount) {
        this.searchId = searchId;
        this.timetableNumber = timetableNumber;
        this.routeLabel = routeLabel;
        this.dayType = dayType;
        this.departureCount = departureCount;
    }

    public Long getId() { return id; }
    public Long getSearchId() { return searchId; }
    public String getTimetableNumber() { return timetableNumber; }
    public String getRouteLabel() { return routeLabel; }
    public String getDayType() { return dayType; }
    public int getDepartureCount() { return departureCount; }
}
