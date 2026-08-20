package za.co.commuttr.api.dto;

import java.util.List;

/**
 * Payloads for /api/health, /api/routes, /api/routes/{id} and /api/timetables/{id}.
 *
 * <p>Record component order is the JSON key order the FastAPI service produced, and the
 * global SNAKE_CASE naming strategy turns {@code letterGroup} into {@code letter_group}.
 */
public final class CatalogDtos {

    private CatalogDtos() { }

    /** GET /api/health */
    public record HealthResponse(String status, long timetables) { }

    /** A row of GET /api/routes (carries the timetable count). */
    public record RouteSummaryDto(Integer id,
                                  String name,
                                  String origin,
                                  String destination,
                                  String letterGroup,
                                  Long timetableCount) { }

    public record RoutesResponse(List<RouteSummaryDto> routes) { }

    /** The route object inside GET /api/routes/{id} — no timetable count here. */
    public record RouteDto(Integer id,
                           String name,
                           String origin,
                           String destination,
                           String letterGroup) { }

    /** A timetable row inside GET /api/routes/{id}. Dates are ISO strings or null. */
    public record TimetableSummaryDto(Integer id,
                                      String timetableNumber,
                                      Boolean isPublicHoliday,
                                      String effectiveFrom,
                                      String effectiveTo,
                                      String pdfFilename,
                                      String pdfUrl,
                                      Integer pageCount,
                                      String parseStatus) { }

    public record RouteDetailResponse(RouteDto route, List<TimetableSummaryDto> timetables) { }

    /** The timetable header inside GET /api/timetables/{id}. */
    public record TimetableHeaderDto(Integer id,
                                     String timetableNumber,
                                     Boolean isPublicHoliday,
                                     String effectiveFrom,
                                     String effectiveTo,
                                     String pdfFilename,
                                     String pdfUrl,
                                     Integer pageCount,
                                     Integer routeId,
                                     String routeName) { }

    public record NoteDto(String code, String description) { }

    public record ScheduleStopDto(Integer stopSequence, String name, Double lat, Double lon) { }

    /** One grid cell. departureTime is "HH:MM" or null. */
    public record CellDto(Integer stopSequence,
                          String cellType,
                          String departureTime,
                          String noteCode,
                          String rawValue) { }

    public record TripDto(Integer tripIndex, List<String> noteCodes, List<CellDto> cells) { }

    public record ScheduleDto(Integer id,
                              Integer pageNumber,
                              Integer directionIndex,
                              String directionLabel,
                              String dayType,
                              String dayLabel,
                              String sectionTimetableNumber,
                              Boolean noService,
                              List<ScheduleStopDto> stops,
                              List<TripDto> trips) { }

    public record TimetableDetailResponse(TimetableHeaderDto timetable,
                                          List<NoteDto> notes,
                                          List<ScheduleDto> schedules) { }
}
