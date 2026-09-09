package za.co.commuttr.api.service;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import za.co.commuttr.api.domain.Route;
import za.co.commuttr.api.domain.Schedule;
import za.co.commuttr.api.domain.Trip;
import za.co.commuttr.api.dto.CatalogDtos.CellDto;
import za.co.commuttr.api.dto.CatalogDtos.AboutResponse;
import za.co.commuttr.api.dto.CatalogDtos.HealthResponse;
import za.co.commuttr.api.dto.CatalogDtos.OperatorSummaryDto;
import za.co.commuttr.api.dto.CatalogDtos.NoteDto;
import za.co.commuttr.api.dto.CatalogDtos.RouteDetailResponse;
import za.co.commuttr.api.dto.CatalogDtos.RouteDto;
import za.co.commuttr.api.dto.CatalogDtos.RouteSummaryDto;
import za.co.commuttr.api.dto.CatalogDtos.RoutesResponse;
import za.co.commuttr.api.dto.CatalogDtos.ScheduleDto;
import za.co.commuttr.api.dto.CatalogDtos.ScheduleStopDto;
import za.co.commuttr.api.dto.CatalogDtos.TimetableDetailResponse;
import za.co.commuttr.api.dto.CatalogDtos.TimetableHeaderDto;
import za.co.commuttr.api.dto.CatalogDtos.TimetableSummaryDto;
import za.co.commuttr.api.dto.CatalogDtos.TripDto;
import za.co.commuttr.api.dto.StopDtos.AreasResponse;
import za.co.commuttr.api.dto.StopDtos.OperatorDto;
import za.co.commuttr.api.dto.StopDtos.OperatorsResponse;
import za.co.commuttr.api.repo.ScheduleRepository;
import za.co.commuttr.api.repo.ScheduleStopRepository;
import za.co.commuttr.api.repo.RouteRepository;
import za.co.commuttr.api.repo.StopTimeRepository;
import za.co.commuttr.api.repo.TimetableNoteRepository;
import za.co.commuttr.api.repo.TimetableRepository;
import za.co.commuttr.api.repo.TripRepository;
import za.co.commuttr.api.repo.projection.Projections.CellRow;
import za.co.commuttr.api.repo.projection.Projections.TimetableDetailRow;
import za.co.commuttr.api.web.ApiException;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The read-only catalogue endpoints: health, routes, timetables and areas.
 * Ported from {@code gabs_scraper/api.py}.
 */
@Service
@Transactional(readOnly = true)
public class CatalogService {

    /** For the two aggregate queries behind /api/about, which no repository owns. */
    @PersistenceContext
    private EntityManager em;

    private final RouteRepository routes;
    private final TimetableRepository timetables;
    private final TimetableNoteRepository notes;
    private final ScheduleRepository schedules;
    private final ScheduleStopRepository scheduleStops;
    private final TripRepository trips;
    private final StopTimeRepository stopTimes;

    public CatalogService(RouteRepository routes,
                          TimetableRepository timetables,
                          TimetableNoteRepository notes,
                          ScheduleRepository schedules,
                          ScheduleStopRepository scheduleStops,
                          TripRepository trips,
                          StopTimeRepository stopTimes) {
        this.routes = routes;
        this.timetables = timetables;
        this.notes = notes;
        this.schedules = schedules;
        this.scheduleStops = scheduleStops;
        this.trips = trips;
        this.stopTimes = stopTimes;
    }

    /** GET /api/health */
    public HealthResponse health() {
        return new HealthResponse("ok", timetables.count());
    }

    /**
     * GET /api/about - whose timetables these are and when they were last read.
     *
     * A journey planner is only as true as the paper behind it, and that paper has a date
     * on it. Answered from the data rather than written into the page, so it cannot quietly
     * become a lie: some of what is loaded took effect in 2021, and a rider deciding
     * whether to trust a departure time is entitled to know that.
     */
    @SuppressWarnings("unchecked")
    public AboutResponse about() {
        List<Object[]> rows = (List<Object[]>) em.createNativeQuery("""
                SELECT o.code, o.name, o.kind,
                       count(DISTINCT r.id), count(DISTINCT t.id)
                FROM operator o
                LEFT JOIN route r     ON r.operator_id = o.id
                LEFT JOIN timetable t ON t.route_id = r.id
                GROUP BY o.code, o.name, o.kind
                ORDER BY count(DISTINCT r.id) DESC
                """).getResultList();

        List<OperatorSummaryDto> operators = rows.stream()
                .map(r -> new OperatorSummaryDto((String) r[0], (String) r[1], (String) r[2],
                        ((Number) r[3]).longValue(), ((Number) r[4]).longValue()))
                .toList();

        Object[] dates = (Object[]) em.createNativeQuery("""
                SELECT CAST(max(scraped_at) AS text),
                       CAST(min(effective_from) AS text),
                       CAST(max(effective_from) AS text),
                       (SELECT count(*) FROM stop)
                FROM timetable
                """).getSingleResult();

        return new AboutResponse(operators, (String) dates[0], (String) dates[1],
                (String) dates[2], ((Number) dates[3]).longValue());
    }

    /** GET /api/routes */
    public RoutesResponse listRoutes(String q, String letter) {
        String namePattern = (q == null || q.isEmpty()) ? null : "%" + q + "%";
        String letterGroup = (letter == null || letter.isEmpty()) ? null : letter.toUpperCase();

        List<RouteSummaryDto> rows = routes.search(namePattern, letterGroup).stream()
                .map(r -> new RouteSummaryDto(r.getId(), r.getName(), r.getOrigin(),
                        r.getDestination(), r.getLetterGroup(), r.getTimetableCount()))
                .toList();
        return new RoutesResponse(rows);
    }

    /** GET /api/routes/{route_id} */
    public RouteDetailResponse getRoute(Integer routeId) {
        Route route = routes.findById(routeId)
                .orElseThrow(() -> ApiException.notFound("route not found"));

        List<TimetableSummaryDto> rows = timetables.findRowsByRouteId(routeId).stream()
                .map(t -> new TimetableSummaryDto(
                        t.getId(),
                        t.getTimetableNumber(),
                        t.getIsPublicHoliday(),
                        ApiFormat.date(t.getEffectiveFrom()),
                        ApiFormat.date(t.getEffectiveTo()),
                        t.getPdfFilename(),
                        t.getPdfUrl(),
                        t.getPageCount(),
                        t.getParseStatus()))
                .toList();

        RouteDto dto = new RouteDto(route.getId(), route.getName(), route.getOrigin(),
                route.getDestination(), route.getLetterGroup());
        return new RouteDetailResponse(dto, rows);
    }

    /** GET /api/timetables/{timetable_id} — the full render payload. */
    public TimetableDetailResponse getTimetable(Integer timetableId) {
        TimetableDetailRow t = timetables.findDetailById(timetableId)
                .orElseThrow(() -> ApiException.notFound("timetable not found"));

        TimetableHeaderDto header = new TimetableHeaderDto(
                t.getId(),
                t.getTimetableNumber(),
                t.getIsPublicHoliday(),
                ApiFormat.date(t.getEffectiveFrom()),
                ApiFormat.date(t.getEffectiveTo()),
                t.getPdfFilename(),
                t.getPdfUrl(),
                t.getPageCount(),
                t.getRouteId(),
                t.getRouteName());

        List<NoteDto> noteDtos = notes.findByTimetableIdOrderByCodeAsc(timetableId).stream()
                .map(n -> new NoteDto(n.getCode(), n.getDescription()))
                .toList();

        List<ScheduleDto> scheduleDtos = new ArrayList<>();
        for (Schedule sc : schedules.findForTimetable(timetableId)) {
            scheduleDtos.add(buildSchedule(sc));
        }

        return new TimetableDetailResponse(header, noteDtos, scheduleDtos);
    }

    private ScheduleDto buildSchedule(Schedule sc) {
        Integer scheduleId = sc.getId();

        List<ScheduleStopDto> stops = scheduleStops.findStopsForSchedule(scheduleId).stream()
                .map(s -> new ScheduleStopDto(s.getStopSequence(), s.getName(), s.getLat(), s.getLon()))
                .toList();

        // Bucket the grid cells onto their trip. Cells whose trip is missing are dropped,
        // exactly as the Python `if ti in trips` guard did.
        Map<Integer, List<CellDto>> cellsByTrip = new LinkedHashMap<>();
        List<Trip> tripRows = trips.findByScheduleIdOrderByTripIndexAsc(scheduleId);
        for (Trip trip : tripRows) {
            cellsByTrip.put(trip.getTripIndex(), new ArrayList<>());
        }
        for (CellRow cell : stopTimes.findCellsForSchedule(scheduleId)) {
            List<CellDto> bucket = cellsByTrip.get(cell.getTripIndex());
            if (bucket != null) {
                bucket.add(new CellDto(
                        cell.getStopSequence(),
                        cell.getCellType(),
                        ApiFormat.time(cell.getDepartureTime()),
                        cell.getNoteCode(),
                        cell.getRawValue()));
            }
        }

        List<TripDto> tripDtos = tripRows.stream()
                .map(trip -> new TripDto(
                        trip.getTripIndex(),
                        trip.getNoteCodes() == null ? null : Arrays.asList(trip.getNoteCodes()),
                        cellsByTrip.get(trip.getTripIndex())))
                .toList();

        return new ScheduleDto(
                sc.getId(),
                sc.getPageNumber(),
                sc.getDirectionIndex(),
                sc.getDirectionLabel(),
                sc.getDayType(),
                sc.getDayLabel(),
                sc.getSectionTimetableNumber(),
                sc.isNoService(),
                stops,
                tripDtos);
    }

    /** GET /api/areas */
    public AreasResponse areas() {
        return new AreasResponse(routes.findAreaNames(), routes.findAreasWithRail());
    }

    /** Every operator, with enough detail for the UI to know which ones are ready. */
    public OperatorsResponse operators() {
        return new OperatorsResponse(routes.operatorTotals().stream()
                .map(r -> new OperatorDto(
                        (String) r[0], (String) r[1], (String) r[2],
                        ((Number) r[3]).intValue(), ((Number) r[4]).longValue()))
                .toList());
    }
}
