package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

/** Maps sql/schema.sql :: timetable_note, the per-timetable footnote codes. */
@Entity
@Immutable
@Table(name = "timetable_note")
public class TimetableNote {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "timetable_id", nullable = false)
    private Integer timetableId;

    @Column(name = "code", nullable = false)
    private String code;

    @Column(name = "description")
    private String description;

    public Integer getId() { return id; }
    public Integer getTimetableId() { return timetableId; }
    public String getCode() { return code; }
    public String getDescription() { return description; }
}
