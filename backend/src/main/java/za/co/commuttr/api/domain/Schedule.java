package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

import java.time.LocalDate;

/** Maps sql/schema.sql :: schedule, a (direction, day-type) block within a timetable. */
@Entity
@Immutable
@Table(name = "schedule")
public class Schedule {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "timetable_id", nullable = false)
    private Integer timetableId;

    @Column(name = "page_number")
    private Integer pageNumber;

    @Column(name = "direction_index")
    private Integer directionIndex;

    @Column(name = "direction_label")
    private String directionLabel;

    /** One of WEEKDAY, SATURDAY, SUNDAY, PUBLIC_HOLIDAY, OTHER. */
    @Column(name = "day_type")
    private String dayType;

    @Column(name = "day_label")
    private String dayLabel;

    @Column(name = "section_timetable_number")
    private String sectionTimetableNumber;

    @Column(name = "section_effective_date")
    private LocalDate sectionEffectiveDate;

    @Column(name = "no_service", nullable = false)
    private boolean noService;

    public Integer getId() { return id; }
    public Integer getTimetableId() { return timetableId; }
    public Integer getPageNumber() { return pageNumber; }
    public Integer getDirectionIndex() { return directionIndex; }
    public String getDirectionLabel() { return directionLabel; }
    public String getDayType() { return dayType; }
    public String getDayLabel() { return dayLabel; }
    public String getSectionTimetableNumber() { return sectionTimetableNumber; }
    public LocalDate getSectionEffectiveDate() { return sectionEffectiveDate; }
    public boolean isNoService() { return noService; }
}
