package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** Maps sql/schema.sql :: trip, a grid column (one bus run) of a schedule. */
@Entity
@Immutable
@Table(name = "trip")
public class Trip {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "schedule_id", nullable = false)
    private Integer scheduleId;

    @Column(name = "trip_index", nullable = false)
    private Integer tripIndex;

    /** PostgreSQL TEXT[] of footnote codes. */
    @JdbcTypeCode(SqlTypes.ARRAY)
    @Column(name = "note_codes")
    private String[] noteCodes;

    public Integer getId() { return id; }
    public Integer getScheduleId() { return scheduleId; }
    public Integer getTripIndex() { return tripIndex; }
    public String[] getNoteCodes() { return noteCodes; }
}
