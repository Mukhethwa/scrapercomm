package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.OffsetDateTime;

/** A row of {@code place_search}: what somebody looked for in the stop list. */
@Entity
@Table(name = "place_search")
public class PlaceSearch {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id")
    private String deviceId;

    @Column(name = "client")
    private String client;

    @Column(name = "query", nullable = false)
    private String query;

    @Column(name = "result_count", nullable = false)
    private int resultCount;

    @Column(name = "chosen_stop_id")
    private Integer chosenStopId;

    @Column(name = "searched_at", nullable = false)
    private OffsetDateTime searchedAt;

    protected PlaceSearch() { }

    public PlaceSearch(String deviceId, String client, String query, int resultCount,
                       Integer chosenStopId, OffsetDateTime searchedAt) {
        this.deviceId = deviceId;
        this.client = client;
        this.query = query;
        this.resultCount = resultCount;
        this.chosenStopId = chosenStopId;
        this.searchedAt = searchedAt;
    }

    public Long getId() { return id; }
    public String getQuery() { return query; }
    public int getResultCount() { return resultCount; }
    public Integer getChosenStopId() { return chosenStopId; }
}
