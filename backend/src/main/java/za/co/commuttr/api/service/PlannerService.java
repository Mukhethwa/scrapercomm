package za.co.commuttr.api.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import za.co.commuttr.api.analytics.SearchAnalyticsEvent;
import za.co.commuttr.api.dto.PlanDtos.LegHitDto;
import za.co.commuttr.api.dto.PlanDtos.LocateResponse;
import za.co.commuttr.api.dto.PlanDtos.NearbyOriginDto;
import za.co.commuttr.api.dto.PlanDtos.NearbyOriginsResponse;
import za.co.commuttr.api.dto.PlanDtos.PlanDepartureDto;
import za.co.commuttr.api.dto.PlanDtos.PlanOptionDto;
import za.co.commuttr.api.dto.PlanDtos.PlanResponse;
import za.co.commuttr.api.dto.PlanDtos.PlanSegmentStopDto;
import za.co.commuttr.api.dto.PlanDtos.TripNoteDto;
import za.co.commuttr.api.dto.PlanDtos.TripStopDto;
import za.co.commuttr.api.dto.PlanDtos.TripStopsResponse;
import za.co.commuttr.api.dto.StopDtos.DownstreamStopDto;
import za.co.commuttr.api.dto.StopDtos.PinDto;
import za.co.commuttr.api.dto.StopDtos.ReachablePointResponse;
import za.co.commuttr.api.repo.LegGeometryRepository;
import za.co.commuttr.api.repo.ScheduleRepository;
import za.co.commuttr.api.repo.ScheduleStopRepository;
import za.co.commuttr.api.repo.StopRepository;
import za.co.commuttr.api.repo.StopTimeRepository;
import za.co.commuttr.api.repo.projection.Projections.DirectServiceRow;
import za.co.commuttr.api.repo.projection.Projections.DownstreamStopRow;
import za.co.commuttr.api.repo.projection.Projections.LegGeometryRow;
import za.co.commuttr.api.repo.projection.Projections.PinAnchorRow;
import za.co.commuttr.api.repo.projection.Projections.ReachableRow;
import za.co.commuttr.api.repo.projection.Projections.ScheduleMetaRow;
import za.co.commuttr.api.repo.projection.Projections.SegmentStopWithIdRow;
import za.co.commuttr.api.repo.projection.Projections.StopAnchorRow;
import za.co.commuttr.api.repo.projection.Projections.StopRow;
import za.co.commuttr.api.repo.projection.Projections.TripStopRow;
import za.co.commuttr.api.web.ApiException;

import java.time.LocalTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

/**
 * Journey planning over official timing points AND unofficial pin locations. A direct
 * port of {@code gabs_scraper/planner.py}.
 *
 * <p>An <em>endpoint</em> is either a named stop or a pin. Each endpoint resolves to a
 * set of <em>anchors</em> — one per (schedule, trip) it touches — carrying a fractional
 * position along the trip's stop sequence and a departure/arrival time:
 *
 * <ul>
 *   <li>stop -&gt; position = stop_sequence, exact time.</li>
 *   <li>pin  -&gt; matched to legs whose real road path passes within a threshold;
 *       position = seqA + f, time = interpolate(tA, tB, f), flagged approximate.</li>
 * </ul>
 *
 * <p>A journey exists on a trip when a board anchor precedes an alight anchor. Results
 * are grouped by physical service (timetable number + direction + day type). Direct
 * buses only.
 */
@Service
@Transactional(readOnly = true)
public class PlannerService {

    private static final Logger log = LoggerFactory.getLogger(PlannerService.class);

    /** Tolerance for imprecise pins and place-search centroids. */
    public static final double DEFAULT_THRESHOLD_M = 700.0;

    private static final double DEFAULT_RADIUS_M = 2500.0;
    private static final int NEARBY_LIMIT = 8;
    private static final int NEARBY_CANDIDATES = 60;

    private final StopRepository stops;
    private final StopTimeRepository stopTimes;
    private final ScheduleStopRepository scheduleStops;
    private final ScheduleRepository schedules;
    private final LegGeometryRepository legGeometry;
    private final ObjectMapper objectMapper;
    private final ApplicationEventPublisher events;

    public PlannerService(StopRepository stops,
                          StopTimeRepository stopTimes,
                          ScheduleStopRepository scheduleStops,
                          ScheduleRepository schedules,
                          LegGeometryRepository legGeometry,
                          ObjectMapper objectMapper,
                          ApplicationEventPublisher events) {
        this.stops = stops;
        this.stopTimes = stopTimes;
        this.scheduleStops = scheduleStops;
        this.schedules = schedules;
        this.legGeometry = legGeometry;
        this.objectMapper = objectMapper;
        this.events = events;
    }

    // ---------------------------------------------------------------- anchors

    /** Identifies one bus run: a (schedule, trip) pair. */
    private record AnchorKey(int scheduleId, int tripIndex) implements Comparable<AnchorKey> {
        @Override
        public int compareTo(AnchorKey other) {
            int bySchedule = Integer.compare(scheduleId, other.scheduleId);
            return bySchedule != 0 ? bySchedule : Integer.compare(tripIndex, other.tripIndex);
        }
    }

    /**
     * Where an endpoint sits on one bus run.
     *
     * @param minutes minutes past midnight; an Integer for an exact stop, a Double when
     *                interpolated along a leg, so the JSON keeps Python's number shape
     */
    private record Anchor(double position, Number minutes, String raw, boolean approx,
                          String label, double distanceM) { }

    /** {@code planner._stop_anchors} */
    private Map<AnchorKey, List<Anchor>> stopAnchors(Integer stopId) {
        Map<AnchorKey, List<Anchor>> anchors = new TreeMap<>();
        for (StopAnchorRow r : stopTimes.findStopAnchors(stopId)) {
            anchors.computeIfAbsent(new AnchorKey(r.getScheduleId(), r.getTripIndex()),
                            k -> new ArrayList<>())
                    .add(new Anchor(r.getStopSequence().doubleValue(),
                            ApiFormat.minutes(r.getDepartureTime()),
                            r.getRawValue(), false, r.getName(), 0.0));
        }
        return anchors;
    }

    /** {@code planner._pin_anchors} */
    private Map<AnchorKey, List<Anchor>> pinAnchors(double lat, double lon, double thresholdM) {
        Map<AnchorKey, List<Anchor>> anchors = new TreeMap<>();
        for (LegHitDto leg : locatePoint(lat, lon, thresholdM)) {
            double f = leg.fraction();
            for (PinAnchorRow r : stopTimes.findPinAnchors(leg.toStopId(), leg.fromStopId())) {
                Integer ma = ApiFormat.minutes(r.getTimeA());
                Integer mb = ApiFormat.minutes(r.getTimeB());

                Number minutes = null;
                if (ma != null && mb != null) {
                    minutes = ma + f * (mb - ma);
                } else if (ma != null) {
                    minutes = ma;
                } else if (mb != null) {
                    minutes = mb;
                }

                String raw = minutes == null ? "via" : ApiFormat.minutesToClock(minutes);
                anchors.computeIfAbsent(new AnchorKey(r.getScheduleId(), r.getTripIndex()),
                                k -> new ArrayList<>())
                        .add(new Anchor(r.getStopSequence() + f, minutes, raw, true,
                                "near " + r.getNameA() + "–" + r.getNameB(),
                                leg.distanceM()));
            }
        }
        return anchors;
    }

    /** {@code planner.endpoint_anchors} */
    private Map<AnchorKey, List<Anchor>> endpointAnchors(EndpointRef ep, double thresholdM) {
        return ep.isStop()
                ? stopAnchors(ep.stopId())
                : pinAnchors(ep.lat(), ep.lon(), thresholdM);
    }

    // ---------------------------------------------------------- point location

    /**
     * {@code planner.locate_point} — legs whose real road path passes within the
     * threshold of the point, nearest first.
     */
    public List<LegHitDto> locatePoint(double lat, double lon, double thresholdM) {
        double deg = thresholdM / 111000.0 + 0.001;

        List<LegHitDto> hits = new ArrayList<>();
        for (LegGeometryRow row : legGeometry.findNearPoint(deg, lat, lon)) {
            double[][] path = parsePath(row.getPath());
            double[] located = GeoUtils.locateOnPath(path, row.getLengthM(), lat, lon);
            if (located[0] <= thresholdM) {
                hits.add(new LegHitDto(row.getFromStopId(), row.getToStopId(),
                        ApiFormat.roundTo(located[0], 1), ApiFormat.roundTo(located[1], 4)));
            }
        }
        hits.sort(Comparator.comparingDouble(LegHitDto::distanceM));
        return hits;
    }

    /** GET /api/locate */
    public LocateResponse locate(double lat, double lon) {
        return new LocateResponse(lat, lon, locatePoint(lat, lon, DEFAULT_THRESHOLD_M));
    }

    /** The JSONB {@code [[lat,lon], ...]} column, decoded defensively. */
    private double[][] parsePath(String json) {
        if (json == null || json.isBlank()) {
            return new double[0][];
        }
        try {
            JsonNode root = objectMapper.readTree(json);
            if (!root.isArray()) {
                return new double[0][];
            }
            List<double[]> points = new ArrayList<>(root.size());
            for (JsonNode point : root) {
                if (point.isArray() && point.size() >= 2) {
                    points.add(new double[] { point.get(0).asDouble(), point.get(1).asDouble() });
                }
            }
            return points.toArray(new double[0][]);
        } catch (Exception ex) {
            log.warn("Skipping unparseable leg_geometry.path: {}", ex.toString());
            return new double[0][];
        }
    }

    // ------------------------------------------------------- segment + geometry

    /** {@code planner._segment} — inclusive of the stop just past the alight position. */
    private List<PlanSegmentStopDto> segment(Integer scheduleId, double fromPos, double toPos) {
        return scheduleStops.findSegmentWithIds(scheduleId, (int) fromPos, (int) toPos + 1).stream()
                .map(PlannerService::toPlanSegmentStop)
                .toList();
    }

    private static PlanSegmentStopDto toPlanSegmentStop(SegmentStopWithIdRow r) {
        return new PlanSegmentStopDto(r.getStopId(), r.getName(), r.getLat(), r.getLon(),
                r.getStopSequence());
    }

    /**
     * {@code planner._road_path} — the road the passenger actually rides: nothing before
     * boarding, nothing after alighting.
     *
     * <p>{@code seg} spans the <em>enclosing</em> timing points ({@code (int) fromPos} to
     * {@code (int) toPos + 1}), because a leg's geometry only exists between two of them.
     * The ride itself starts wherever the boarding endpoint really is — exactly at a
     * timing point, or a fraction along the leg that follows it. Drawing the whole
     * enclosing range put road on the map the passenger is never on, which is what made
     * the bus look like it detoured to collect them from an unofficial stop.
     */
    private List<double[]> roadPath(List<PlanSegmentStopDto> seg, double fromPos, double toPos) {
        int lo = (int) fromPos;
        int hi = (int) toPos + (toPos > (int) toPos ? 1 : 0);
        double headF = fromPos - lo;              // 0.0 when boarding at a timing point
        double tailF = toPos - (int) toPos;       // 0.0 when alighting at a timing point

        List<Integer> ids = seg.stream()
                .filter(s -> s.stopId() != null
                        && s.stopSequence() >= lo && s.stopSequence() <= hi)
                .map(PlanSegmentStopDto::stopId)
                .filter(Objects::nonNull)
                .toList();
        if (ids.size() < 2) {
            return List.of();
        }

        int legCount = ids.size() - 1;
        List<double[]> full = new ArrayList<>();
        for (int i = 0; i < legCount; i++) {
            double[][] leg = legPath(ids.get(i), ids.get(i + 1));
            if (leg.length == 0) {
                continue;
            }

            double startF = (i == 0) ? headF : 0.0;
            double endF = (i == legCount - 1 && tailF > 0) ? tailF : 1.0;

            List<double[]> points;
            if (startF > 0 || endF < 1) {
                points = GeoUtils.slicePath(leg, startF, endF);
            } else {
                points = new ArrayList<>(leg.length);
                for (double[] p : leg) {
                    points.add(p);
                }
            }
            if (points.isEmpty()) {
                continue;
            }

            int start = 0;
            if (!full.isEmpty() && GeoUtils.samePoint(full.get(full.size() - 1), points.get(0))) {
                start = 1; // do not repeat the shared timing point
            }
            for (int p = start; p < points.size(); p++) {
                full.add(points.get(p));
            }
        }
        return full;
    }

    /** Cached road geometry for one leg, or a straight line if none was fetched. */
    private double[][] legPath(Integer a, Integer b) {
        double[][] path = parsePath(legGeometry.findPathJson(a, b).orElse(null));
        return path.length == 0 ? straightLine(a, b) : path;
    }

    private double[][] straightLine(Integer a, Integer b) {
        Map<Integer, StopRow> coords = new HashMap<>();
        for (StopRow row : stops.findPair(a, b)) {
            coords.put(row.getId(), row);
        }
        StopRow ca = coords.get(a);
        StopRow cb = coords.get(b);
        if (ca == null || cb == null || ca.getLat() == null || cb.getLat() == null) {
            return new double[0][];
        }
        return new double[][] {
                { ca.getLat(), ca.getLon() },
                { cb.getLat(), cb.getLon() },
        };
    }

    // ------------------------------------------------------------- journeys

    private record GroupKey(String timetableNumber, String directionLabel, String dayType) { }

    private static final class PlanGroup {
        String timetableNumber;
        String routeLabel;
        String dayType;
        String dayLabel;
        List<PlanSegmentStopDto> segmentStops;
        List<double[]> roadPath;
        final List<PlanDepartureDto> departures = new ArrayList<>();
        final Set<List<String>> seen = new HashSet<>();
        boolean boardApprox;
        boolean alightApprox;
        String boardLabel;
        String alightLabel;
    }

    /** {@code planner.resolve_journeys} */
    public List<PlanOptionDto> resolveJourneys(EndpointRef fromEp, EndpointRef toEp, double thresholdM) {
        Map<AnchorKey, List<Anchor>> board = endpointAnchors(fromEp, thresholdM);
        Map<AnchorKey, List<Anchor>> alight = endpointAnchors(toEp, thresholdM);

        // Candidate journeys per bus run: earliest board, first alight after it.
        // Iteration follows the natural (schedule, trip) order rather than Python's
        // set-intersection order, which makes the grouping deterministic run to run.
        record Candidate(AnchorKey key, Anchor board, Anchor alight) { }
        List<Candidate> candidates = new ArrayList<>();

        for (Map.Entry<AnchorKey, List<Anchor>> entry : board.entrySet()) {
            List<Anchor> alightAnchors = alight.get(entry.getKey());
            if (alightAnchors == null) {
                continue;
            }
            Anchor b = earliestByPosition(entry.getValue());
            Anchor a = alightAnchors.stream()
                    .filter(x -> x.position() > b.position() && timeConsistent(b, x))
                    .min(Comparator.comparingDouble(Anchor::position))
                    .orElse(null);
            if (a != null) {
                candidates.add(new Candidate(entry.getKey(), b, a));
            }
        }

        Map<Integer, ScheduleMetaRow> meta = scheduleMeta(
                candidates.stream().map(c -> c.key().scheduleId()).distinct().toList());

        Map<GroupKey, PlanGroup> groups = new LinkedHashMap<>();
        Map<Integer, List<PlanSegmentStopDto>> segmentCache = new HashMap<>();

        for (Candidate c : candidates) {
            ScheduleMetaRow m = meta.get(c.key().scheduleId());
            if (m == null) {
                continue;
            }
            GroupKey gkey = new GroupKey(m.getTimetableNumber(), m.getDirectionLabel(), m.getDayType());
            PlanGroup g = groups.get(gkey);
            if (g == null) {
                List<PlanSegmentStopDto> seg = segmentCache.computeIfAbsent(
                        c.key().scheduleId(),
                        id -> segment(id, c.board().position(), c.alight().position()));
                g = new PlanGroup();
                g.timetableNumber = m.getTimetableNumber();
                g.routeLabel = m.getDirectionLabel();
                g.dayType = m.getDayType();
                g.dayLabel = m.getDayLabel();
                g.segmentStops = seg;
                g.roadPath = roadPath(seg, c.board().position(), c.alight().position());
                g.boardApprox = c.board().approx();
                g.alightApprox = c.alight().approx();
                g.boardLabel = c.board().label();
                g.alightLabel = c.alight().label();
                groups.put(gkey, g);
            }

            List<String> signature = Arrays.asList(c.board().raw(), c.alight().raw());
            if (!g.seen.add(signature)) {
                continue;
            }
            g.departures.add(new PlanDepartureDto(
                    c.board().raw(), c.board().approx(), c.board().minutes(),
                    c.alight().raw(), c.alight().approx(), c.alight().minutes(),
                    c.key().scheduleId(), c.key().tripIndex(),
                    // source trip + segment range, so the UI can fetch a stop-by-stop breakdown
                    Math.max(0, (int) Math.ceil(c.board().position() - 1e-6)),
                    (int) (c.alight().position() + 1e-6)));
        }

        List<PlanOptionDto> options = new ArrayList<>(groups.size());
        for (PlanGroup g : groups.values()) {
            g.departures.sort(planDepartureOrder());
            options.add(new PlanOptionDto(
                    g.timetableNumber, g.routeLabel, g.dayType, g.dayLabel,
                    g.segmentStops, g.roadPath, List.copyOf(g.departures),
                    g.boardApprox, g.alightApprox, g.boardLabel, g.alightLabel));
        }
        options.sort(Comparator
                .comparingInt((PlanOptionDto o) -> DayTypes.order(o.dayType()))
                .thenComparing(PlanOptionDto::routeLabel,
                        Comparator.nullsFirst(Comparator.naturalOrder())));
        return options;
    }

    private static Anchor earliestByPosition(List<Anchor> anchors) {
        return anchors.stream().min(Comparator.comparingDouble(Anchor::position)).orElseThrow();
    }

    /** Alighting must not predate boarding by more than the one-minute rounding slack. */
    private static boolean timeConsistent(Anchor board, Anchor alight) {
        if (board.minutes() == null || alight.minutes() == null) {
            return true;
        }
        return alight.minutes().doubleValue() >= board.minutes().doubleValue() - 1;
    }

    /** Timed departures first, then in departure order. */
    private static Comparator<PlanDepartureDto> planDepartureOrder() {
        return Comparator
                .comparing((PlanDepartureDto d) -> d.boardMinutes() == null)
                .thenComparingDouble(d -> d.boardMinutes() == null ? 0 : d.boardMinutes().doubleValue());
    }

    /** {@code planner._schedule_meta} */
    private Map<Integer, ScheduleMetaRow> scheduleMeta(List<Integer> scheduleIds) {
        if (scheduleIds.isEmpty()) {
            return Map.of();
        }
        Map<Integer, ScheduleMetaRow> meta = new HashMap<>();
        for (ScheduleMetaRow row : schedules.findMeta(scheduleIds)) {
            meta.put(row.getId(), row);
        }
        return meta;
    }

    // ------------------------------------------------------------ endpoints

    /** GET /api/plan */
    public PlanResponse plan(EndpointRef fromEp, EndpointRef toEp) {
        long startedAt = System.nanoTime();

        List<PlanOptionDto> options = resolveJourneys(fromEp, toEp, DEFAULT_THRESHOLD_M);

        // The route is found — hand the analytics off and return without waiting for it.
        events.publishEvent(SearchAnalyticsEvent.of("/api/plan", fromEp, toEp,
                options.stream()
                        .map(o -> new SearchAnalyticsEvent.OptionSummary(
                                o.timetableNumber(), o.routeLabel(), o.dayType(),
                                o.departures().size()))
                        .toList(),
                (System.nanoTime() - startedAt) / 1_000_000));

        return new PlanResponse(describe(fromEp), describe(toEp), options);
    }

    /**
     * {@code api._describe} — a named stop renders as the stop object, a pin as
     * {@code {"kind": "pin", ...}}. An unknown stop id renders as null, as before.
     */
    private Object describe(EndpointRef ep) {
        if (ep.isStop()) {
            return stops.findRowById(ep.stopId()).map(StopService::toDto).orElse(null);
        }
        return PinDto.of(ep.lat(), ep.lon());
    }

    /** GET /api/reachable_point */
    public ReachablePointResponse reachablePoint(double lat, double lon) {
        EndpointRef ep = EndpointRef.pin(lat, lon);
        return new ReachablePointResponse(PinDto.of(lat, lon), reachableFrom(ep, DEFAULT_THRESHOLD_M));
    }

    /**
     * {@code planner.reachable_from} — distinct downstream stops on a single bus.
     *
     * <p>One query, not one per bus run. See
     * {@link StopTimeRepository#findReachableFromLegs} for why.
     */
    public List<DownstreamStopDto> reachableFrom(EndpointRef ep, double thresholdM) {
        List<ReachableRow> rows = ep.isStop()
                ? stopTimes.findReachableFromStop(ep.stopId())
                : reachableFromPin(ep, thresholdM);

        return rows.stream()
                .map(r -> new DownstreamStopDto(r.getId(), r.getName(), r.getLat(), r.getLon(),
                        r.getTripCount() == null ? 0 : r.getTripCount().intValue()))
                .toList();
    }

    private List<ReachableRow> reachableFromPin(EndpointRef ep, double thresholdM) {
        List<LegHitDto> legs = locatePoint(ep.lat(), ep.lon(), thresholdM);
        if (legs.isEmpty()) {
            return List.of();
        }
        try {
            // {"a": fromStopId, "b": toStopId, "f": fractionAlongTheLeg}
            List<Map<String, Object>> payload = legs.stream()
                    .map(l -> Map.<String, Object>of(
                            "a", l.fromStopId(), "b", l.toStopId(), "f", l.fraction()))
                    .toList();
            return stopTimes.findReachableFromLegs(objectMapper.writeValueAsString(payload));
        } catch (JsonProcessingException ex) {
            log.warn("Could not encode {} matched legs for reachability: {}",
                    legs.size(), ex.toString());
            return List.of();
        }
    }

    /**
     * GET /api/trip_stops, in travel order.
     *
     * <p>{@code stop_sequence} is the PDF's row order, and for about 4.8% of trips that is
     * not travel order: GABS prints alternative origins as the bottom rows of a grid, so a
     * trip can list CAPE TOWN 06:20 above VREDEKLOOF 05:05 even though Vredekloof is where
     * the bus starts. Rendered as printed it claims the bus reaches its terminus before an
     * earlier stop, and hides the origin's departure time — the one a commuter needs in
     * order to know when to leave home.
     *
     * <p>Published times are the operator's ground truth, so they decide the order. A
     * "via" carries no time of its own but is printed between two timed rows, so it
     * inherits the next timed stop's time; sequence breaks ties, keeping vias in their
     * printed order. Verified to put all 4,819 affected trips into ascending time order.
     */
    public TripStopsResponse tripStops(Integer scheduleId, Integer tripIndex, Integer fromSeq, Integer toSeq) {
        List<TripStopRow> raw = stopTimes.findTripStops(scheduleId, tripIndex, fromSeq, toSeq);
        int n = raw.size();

        // The next published time at or after each row.
        LocalTime[] next = new LocalTime[n];
        LocalTime carry = null;
        for (int i = n - 1; i >= 0; i--) {
            if (raw.get(i).getDepartureTime() != null) {
                carry = raw.get(i).getDepartureTime();
            }
            next[i] = carry;
        }
        // Trailing vias have no later time; fall back to the last one seen.
        LocalTime prev = null;
        for (int i = 0; i < n; i++) {
            if (raw.get(i).getDepartureTime() != null) {
                prev = raw.get(i).getDepartureTime();
            }
            if (next[i] == null) {
                next[i] = prev;
            }
        }

        List<Integer> order = new ArrayList<>(n);
        for (int i = 0; i < n; i++) {
            order.add(i);
        }
        order.sort(Comparator
                .comparing((Integer i) -> next[i] == null)
                .thenComparing(i -> next[i], Comparator.nullsLast(Comparator.naturalOrder()))
                .thenComparing(i -> raw.get(i).getStopSequence()));

        List<TripStopDto> rows = order.stream()
                .map(raw::get)
                .map(r -> new TripStopDto(r.getName(), r.getLat(), r.getLon(), r.getStopSequence(),
                        r.getRawValue(), r.getCellType(), ApiFormat.time(r.getDepartureTime())))
                .toList();
        List<TripNoteDto> notes = stopTimes.findTripNotes(scheduleId, tripIndex).stream()
                .map(note -> new TripNoteDto(note.getCode(), note.getDescription()))
                .toList();
        return new TripStopsResponse(rows, notes);
    }

    /**
     * GET /api/nearby_origins — {@code planner.nearby_origins}. Stops within the radius
     * that DO have a direct bus to the destination, for suggesting an alternative
     * boarding point when the commuter's own stop has none.
     */
    public NearbyOriginsResponse nearbyOrigins(double lat, double lon, Integer toStopId,
                                               Integer radiusM, Integer excludeStopId, String dayType) {
        double radius = radiusM == null ? DEFAULT_RADIUS_M : radiusM;
        double deg = radius / 111000.0 + 0.001;

        record Candidate(double distance, StopRow stop) { }
        List<Candidate> candidates = new ArrayList<>();
        for (StopRow s : stops.findInBoundingBox(lat - deg, lat + deg, lon - deg, lon + deg,
                toStopId, excludeStopId)) {
            if (s.getLat() == null || s.getLon() == null) {
                continue; // half-geocoded stop; the query already excludes null lat
            }
            double d = GeoUtils.haversineM(lat, lon, s.getLat(), s.getLon());
            // Without an explicit exclusion, drop anything essentially on top of the point.
            boolean tooClose = excludeStopId == null && d < 30;
            if (d <= radius && !tooClose) {
                candidates.add(new Candidate(d, s));
            }
        }
        candidates.sort(Comparator.comparingDouble(Candidate::distance));

        List<NearbyOriginDto> out = new ArrayList<>();
        for (Candidate c : candidates.subList(0, Math.min(NEARBY_CANDIDATES, candidates.size()))) {
            DirectServiceRow direct = stopTimes.findDirectService(c.stop().getId(), toStopId, dayType);
            long tripCount = direct == null || direct.getTripCount() == null ? 0 : direct.getTripCount();
            if (tripCount > 0) {
                out.add(new NearbyOriginDto(
                        c.stop().getId(), c.stop().getName(), c.stop().getLat(), c.stop().getLon(),
                        ApiFormat.roundToLong(c.distance()), tripCount,
                        ApiFormat.time(direct.getEarliest())));
            }
            if (out.size() >= NEARBY_LIMIT) {
                break;
            }
        }
        return new NearbyOriginsResponse(out);
    }

    /** Shared 400 for a plan request that named neither a stop nor a coordinate pair. */
    public static ApiException missingEndpoints() {
        return ApiException.badRequest(
                "provide from (stop id) or from_lat/from_lon, and to likewise");
    }
}
