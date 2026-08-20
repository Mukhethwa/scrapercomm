package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

import java.time.LocalTime;

/** Maps sql/schema.sql :: stop_time, one grid cell (trip x stop). */
@Entity
@Immutable
@Table(name = "stop_time")
public class StopTime {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "trip_id", nullable = false)
    private Integer tripId;

    @Column(name = "schedule_stop_id", nullable = false)
    private Integer scheduleStopId;

    /** One of TIME, VIA, NONE. */
    @Column(name = "cell_type", nullable = false)
    private String cellType;

    /** Set only when cellType is TIME. */
    @Column(name = "departure_time")
    private LocalTime departureTime;

    @Column(name = "note_code")
    private String noteCode;

    @Column(name = "raw_value")
    private String rawValue;

    public Integer getId() { return id; }
    public Integer getTripId() { return tripId; }
    public Integer getScheduleStopId() { return scheduleStopId; }
    public String getCellType() { return cellType; }
    public LocalTime getDepartureTime() { return departureTime; }
    public String getNoteCode() { return noteCode; }
    public String getRawValue() { return rawValue; }
}
