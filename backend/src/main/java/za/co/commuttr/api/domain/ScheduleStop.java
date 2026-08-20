package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

/** Maps sql/schema.sql :: schedule_stop, an ordered grid row of a schedule. */
@Entity
@Immutable
@Table(name = "schedule_stop")
public class ScheduleStop {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "schedule_id", nullable = false)
    private Integer scheduleId;

    @Column(name = "stop_id", nullable = false)
    private Integer stopId;

    @Column(name = "stop_sequence", nullable = false)
    private Integer stopSequence;

    public Integer getId() { return id; }
    public Integer getScheduleId() { return scheduleId; }
    public Integer getStopId() { return stopId; }
    public Integer getStopSequence() { return stopSequence; }
}
