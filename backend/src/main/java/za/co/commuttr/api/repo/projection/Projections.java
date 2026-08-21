package za.co.commuttr.api.repo.projection;

import java.time.LocalDate;
import java.time.LocalTime;

/**
 * Interface projections for the native queries in {@code za.co.commuttr.api.repo}.
 *
 * <p>Every native query aliases its columns with <em>quoted</em> camelCase
 * ({@code AS "letterGroup"}) so PostgreSQL preserves the case and Spring Data can bind
 * the tuple straight onto these getters. Unquoted aliases would be folded to lowercase.
 */
public final class Projections {

    private Projections() { }

    /** GET /api/routes row. */
    public interface RouteSummaryRow {
        Integer getId();
        String getName();
        String getOrigin();
        String getDestination();
        String getLetterGroup();
        Long getTimetableCount();
    }

    /** GET /api/routes/{id} -> timetables[] row. */
    public interface TimetableRow {
        Integer getId();
        String getTimetableNumber();
        Boolean getIsPublicHoliday();
        LocalDate getEffectiveFrom();
        LocalDate getEffectiveTo();
        String getPdfFilename();
        String getPdfUrl();
        Integer getPageCount();
        String getParseStatus();
    }

    /** GET /api/timetables/{id} -> timetable header. */
    public interface TimetableDetailRow {
        Integer getId();
        String getTimetableNumber();
        Boolean getIsPublicHoliday();
        LocalDate getEffectiveFrom();
        LocalDate getEffectiveTo();
        String getPdfFilename();
        String getPdfUrl();
        Integer getPageCount();
        Integer getRouteId();
        String getRouteName();
    }

    /** Footnote row. */
    public interface NoteRow {
        String getCode();
        String getDescription();
    }

    /** A stop as the API exposes it. */
    public interface StopRow {
        Integer getId();
        String getName();
        Double getLat();
        Double getLon();
    }

    /** GET /api/stops/{id}/reachable row. */
    public interface ReachableRow {
        Integer getId();
        String getName();
        Double getLat();
        Double getLon();
        Long getTripCount();
        Long getRouteCount();
    }

    /** Ordered stops of a schedule (timetable render payload). */
    public interface ScheduleStopRow {
        Integer getStopSequence();
        String getName();
        Double getLat();
        Double getLon();
    }

    /** A grid cell, still carrying its trip index so cells can be bucketed. */
    public interface CellRow {
        Integer getTripIndex();
        Integer getStopSequence();
        String getCellType();
        LocalTime getDepartureTime();
        String getNoteCode();
        String getRawValue();
    }

    /** A schedule that connects two stops in order (GET /api/journeys). */
    public interface JourneyConnRow {
        Integer getScheduleId();
        String getDirectionLabel();
        String getDayType();
        String getDayLabel();
        Integer getRouteId();
        String getRouteName();
        Integer getTimetableId();
        String getTimetableNumber();
        Integer getSsx();
        Integer getSsy();
        Integer getBseq();
        Integer getAseq();
    }

    /** One board/alight pair on a trip (GET /api/journeys). */
    public interface JourneyDepartureRow {
        LocalTime getBoardTime();
        String getBoardRaw();
        String getBoardType();
        String getNoteCode();
        LocalTime getArriveTime();
        String getArriveRaw();
        String getArriveType();
    }

    /** Segment stop without an id (GET /api/journeys). */
    public interface SegmentStopRow {
        String getName();
        Double getLat();
        Double getLon();
        Integer getStopSequence();
    }

    /** Segment stop with its id (GET /api/plan, needed to stitch road geometry). */
    public interface SegmentStopWithIdRow {
        Integer getStopId();
        String getName();
        Double getLat();
        Double getLon();
        Integer getStopSequence();
    }

    /** GET /api/trip_stops row. */
    public interface TripStopRow {
        String getName();
        Double getLat();
        Double getLon();
        Integer getStopSequence();
        String getRawValue();
        String getCellType();
        LocalTime getDepartureTime();
    }

    /** leg_geometry candidate for point location; path is raw JSON text. */
    public interface LegGeometryRow {
        Integer getFromStopId();
        Integer getToStopId();
        String getPath();
        Double getLengthM();
    }

    /** Anchor of a named stop on a (schedule, trip). */
    public interface StopAnchorRow {
        Integer getScheduleId();
        Integer getTripIndex();
        Integer getStopSequence();
        LocalTime getDepartureTime();
        String getRawValue();
        String getName();
    }

    /** Anchor of a pin, interpolated along the leg A -> B. */
    public interface PinAnchorRow {
        Integer getScheduleId();
        Integer getTripIndex();
        Integer getStopSequence();
        LocalTime getTimeA();
        LocalTime getTimeB();
        String getNameA();
        String getNameB();
    }

    /** Schedule metadata keyed by schedule id (planner grouping). */
    public interface ScheduleMetaRow {
        Integer getId();
        String getDirectionLabel();
        String getDayType();
        String getDayLabel();
        String getTimetableNumber();
    }

    /** Distinct downstream stop reachable from an anchor. */
    public interface DownstreamStopRow {
        Integer getId();
        String getName();
        Double getLat();
        Double getLon();
    }

    /** One two-leg connection: A -> change -> B. */
    public interface TwoLegRow {
        String getDayType();
        Integer getChangeId();
        String getChangeName();

        String getRoute1();
        LocalTime getDep1();
        LocalTime getArr1();
        Integer getSched1();
        Integer getTrip1();
        Integer getFromSeq1();
        Integer getToSeq1();

        String getRoute2();
        LocalTime getDep2();
        /** Raw cell text: may be "via" where no arrival time is published. */
        String getArrRaw2();
        Integer getSched2();
        Integer getTrip2();
        Integer getFromSeq2();
        Integer getToSeq2();

        Integer getWaitMinutes();
        Integer getTotalMinutes();
    }

    /** One three-leg connection: A -> change -> change2 -> B. */
    public interface ThreeLegRow {
        String getDayType();
        Integer getChangeId();
        String getChangeName();
        Integer getChange2Id();
        String getChange2Name();

        String getRoute1();
        LocalTime getDep1();
        LocalTime getArr1();
        Integer getSched1();
        Integer getTrip1();
        Integer getFromSeq1();
        Integer getToSeq1();

        String getRoute2();
        LocalTime getDep2();
        LocalTime getArr2();
        Integer getSched2();
        Integer getTrip2();
        Integer getFromSeq2();
        Integer getToSeq2();

        String getRoute3();
        LocalTime getDep3();
        String getArrRaw3();
        Integer getSched3();
        Integer getTrip3();
        Integer getFromSeq3();
        Integer getToSeq3();

        Integer getWaitMinutes();
        Integer getTotalMinutes();
    }

    /** Aggregate for GET /api/nearby_origins: does this stop reach the destination? */
    public interface DirectServiceRow {
        LocalTime getEarliest();
        Long getTripCount();
    }
}
