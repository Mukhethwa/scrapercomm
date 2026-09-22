package za.co.commuttr.api.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import za.co.commuttr.api.dto.PlanDtos.FareDto;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionFareDto;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionDto;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionLegDto;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionsResponse;
import za.co.commuttr.api.repo.ConnectionRepository;
import za.co.commuttr.api.repo.StopRepository;
import za.co.commuttr.api.repo.projection.Projections.StopRow;
import za.co.commuttr.api.repo.projection.Projections.ThreeLegRow;
import za.co.commuttr.api.repo.projection.Projections.TwoLegRow;
import za.co.commuttr.api.web.ApiException;

import java.util.HashMap;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

/**
 * GET /api/connections — how to get from A to B when no single bus does it.
 *
 * <p>Fewest buses wins. Two legs are searched first and three only if two finds nothing,
 * because a commuter would always rather change once than twice, and because the two-leg
 * search is the cheaper of the two. Within a given number of legs the results are ordered
 * by total journey time, then by time spent waiting.
 */
@Service
@Transactional(readOnly = true)
public class ConnectionService {

    private final StopRepository stops;
    private final ConnectionRepository connections;
    private final int bufferMinutes;
    /**
     * How many journeys to return, now that they are one per departure.
     *
     * Six was the right number when it meant six to show. It is the wrong number for a
     * day's departures: the screen filters what it gets by the rider's own leave-time, so
     * anything not sent is a journey they are told does not exist. Khayelitsha to
     * Kraaifontein has ten departures, the busiest pairs on these lines have around thirty,
     * and forty is a whole day with room to spare.
     */
    private final int maxResults;

    public ConnectionService(StopRepository stops,
                             ConnectionRepository connections,
                             @Value("${commuttr.connections.transfer-buffer-minutes:10}") int bufferMinutes,
                             @Value("${commuttr.connections.max-results:40}") int maxResults) {
        this.stops = stops;
        this.connections = connections;
        this.bufferMinutes = bufferMinutes;
        this.maxResults = maxResults;
    }

    /**
     * How far a rider walks from a place to something they can board.
     *
     * The same distance the planner uses for a direct journey, because it is the same
     * walk. A journey with a change does not start further from home than a journey
     * without one.
     *
     * <p>Now actually the same. This said so and then set its own 1,500m while the planner
     * walked 2,500 - so a place could reach a station directly and not reach it with a
     * change, and the comment describing the intent was the only part that was right. It
     * reads the planner's constant now, so the two cannot drift again.
     */
    private static final double WALK_M = PlannerService.WALK_M;

    /**
     * How many nearby stops of EACH OPERATOR to try for a place, nearest first.
     *
     * Per operator, because the lists are gathered one after another and a flat cap
     * across them starves whoever is gathered last. It was per kind, which was the same
     * thing until MyCiTi arrived: two bus companies then shared one bus allowance, and
     * MyCiTi's dense city stations pushed Golden Arrow's out of it. A rider reaches this
     * list precisely when the direct search found nothing, which is when the operator
     * being crowded out matters most.
     */
    private static final int NEAR_TRIED = 5;

    public ConnectionsResponse connections(Integer fromId, Double fromLat, Double fromLon,
                                           Integer toId, Double toLat, Double toLon) {
        return connections(fromId, fromLat, fromLon, toId, toLat, toLon, null);
    }

    /**
     * @param operator when not null, only this operator's stops are tried at either end.
     *
     * The search takes the first pair of stops that connects, nearest first, across every
     * operator - so from Mowbray it finds two Golden Arrow buses and stops there, and a
     * rider who pressed Metro Rail or MyCiTi was never shown a journey with a change on
     * the network they asked about. Mukhethwa: "the results do not show multi legged
     * journeys for other modes instead of buses".
     *
     * Scoping the ends is enough to scope the journey: a connection changes at one stop
     * row, and no stop row is served by two operators, so both legs belong to whoever
     * owns the ends.
     */
    public ConnectionsResponse connections(Integer fromId, Double fromLat, Double fromLon,
                                           Integer toId, Double toLat, Double toLon,
                                           String operator) {
        return connections(fromId, fromLat, fromLon, null, toId, toLat, toLon, null, operator);
    }

    /**
     * @param fromName what the rider called the starting place, if they chose one by name:
     *                 a stop or station called exactly that is tried first, as in
     *                 {@link PlannerService}, however far the place's coordinates are from it.
     */
    public ConnectionsResponse connections(Integer fromId, Double fromLat, Double fromLon, String fromName,
                                           Integer toId, Double toLat, Double toLon, String toName,
                                           String operator) {
        List<StopRow> fromStops = resolve(fromId, fromLat, fromLon, operator, fromName);
        List<StopRow> toStops = resolve(toId, toLat, toLon, operator, toName);
        if (fromStops.isEmpty() || toStops.isEmpty()) {
            // Scoped to an operator with nothing within walking distance of one end, the
            // honest answer is "no journey", not "no such stop".
            if (operator != null) {
                return new ConnectionsResponse(null, null, null, List.of());
            }
            throw ApiException.notFound("stop not found");
        }

        // Nearest first, and the first pair that connects wins.
        //
        // A place is not one stop, and trying every pair would run this query nine times
        // to no purpose: the nearest stop that can make the journey is the one a rider
        // would use. Trying the next only when the nearer one connects to nothing keeps
        // the usual case at one query and still answers where the closest stop happens to
        // be on the wrong route.
        for (StopRow from : fromStops) {
            for (StopRow to : toStops) {
                ConnectionsResponse found = between(from, to);
                if (!found.connections().isEmpty()) {
                    return found;
                }
            }
        }
        return new ConnectionsResponse(StopService.toDto(fromStops.get(0)),
                StopService.toDto(toStops.get(0)), null, List.of());
    }

    /** A stop id as itself, or a point as the stops a rider could walk to. */
    private List<StopRow> resolve(Integer id, Double lat, Double lon, String operator, String name) {
        List<StopRow> near = resolve(id, lat, lon, operator);
        if (id != null || name == null || name.isBlank()) {
            return near;
        }
        List<StopRow> named = new ArrayList<>(stops.findByExactName(name.trim()).stream()
                .filter(r -> operator == null || operator.equals(r.getOperatorCode()))
                .filter(r -> lat == null || lon == null
                        || GeoUtils.haversineM(lat, lon, r.getLat(), r.getLon()) <= PlannerService.NAMED_STOP_M)
                .toList());
        if (named.isEmpty()) {
            return near;
        }
        java.util.Set<Integer> seen = new java.util.HashSet<>();
        named.forEach(r -> seen.add(r.getId()));
        near.stream().filter(r -> seen.add(r.getId())).forEach(named::add);
        return named;
    }

    private List<StopRow> resolve(Integer id, Double lat, Double lon, String operator) {
        if (id != null) {
            // A named stop of another operator cannot start or end a journey on this one.
            return stops.findRowById(id)
                    .filter(r -> operator == null || operator.equals(r.getOperatorCode()))
                    .map(List::of).orElseGet(List::of);
        }
        if (lat == null || lon == null) {
            return List.of();
        }
        List<StopRow> near = new ArrayList<>();
        List<String> codes = operator == null ? stops.operatorCodesWithStops() : List.of(operator);
        for (String code : codes) {
            near.addAll(stops.findNearestOfOperator(lat, lon, code, WALK_M).stream()
                    .limit(NEAR_TRIED).toList());
        }
        // Nearest first ACROSS both kinds, not trains and then buses.
        //
        // The two lists are gathered one after the other so that a cap cannot spend
        // itself on one network, which is right - but the order they were gathered in
        // then decided the journey, because the first pair that connects wins. Gaylee to
        // Tuscany Glen started at BLACKHEATH station, 1,359m away, with a bus stop at
        // 558m; it ended at MELTON ROSE, 1,767m off, with one at 963m. The rider asked
        // for neither station and was walking to both because rail is gathered first.
        //
        // Which is the same fault the direct planner had, reached by a different road:
        // an end chosen by something that is not how near it is to what was searched.
        near.sort(Comparator.comparingDouble(
                s -> GeoUtils.haversineM(lat, lon, s.getLat(), s.getLon())));
        return near;
    }

    private ConnectionsResponse between(StopRow from, StopRow to) {
        Integer fromId = from.getId();
        Integer toId = to.getId();

        var twoRows = connections.findTwoLegConnections(fromId, toId, bufferMinutes, maxResults);
        if (!twoRows.isEmpty()) {
            Map<Integer, StopRow> coords = coordsFor(
                    twoRows.stream().map(TwoLegRow::getChangeId).toList());
            List<ConnectionDto> two = twoRows.stream().map(r -> toDto(r, from, to, coords)).toList();
            return new ConnectionsResponse(StopService.toDto(from), StopService.toDto(to), 2, two);
        }

        var threeRows = connections.findThreeLegConnections(fromId, toId, bufferMinutes, maxResults);
        if (!threeRows.isEmpty()) {
            Map<Integer, StopRow> coords = coordsFor(threeRows.stream()
                    .flatMap(r -> java.util.stream.Stream.of(r.getChangeId(), r.getChange2Id()))
                    .toList());
            List<ConnectionDto> three = threeRows.stream()
                    .map(r -> toDto(r, from, to, coords)).toList();
            return new ConnectionsResponse(StopService.toDto(from), StopService.toDto(to), 3, three);
        }

        // Genuinely unreachable within three buses.
        return new ConnectionsResponse(StopService.toDto(from), StopService.toDto(to), null, List.of());
    }

    /** Coordinates for the interchange stops, so each leg is a complete endpoint pair. */
    private Map<Integer, StopRow> coordsFor(List<Integer> stopIds) {
        List<Integer> ids = stopIds.stream().filter(java.util.Objects::nonNull).distinct().toList();
        Map<Integer, StopRow> byId = new HashMap<>();
        if (!ids.isEmpty()) {
            stops.findRowsByIds(ids).forEach(r -> byId.put(r.getId(), r));
        }
        return byId;
    }

    private static Double lat(Map<Integer, StopRow> coords, Integer id) {
        StopRow r = coords.get(id);
        return r == null ? null : r.getLat();
    }

    private static Double lon(Map<Integer, StopRow> coords, Integer id) {
        StopRow r = coords.get(id);
        return r == null ? null : r.getLon();
    }

    private static final java.util.regex.Pattern CLOCK =
            java.util.regex.Pattern.compile("^([0-9]{1,2}):([0-9]{2})");

    /**
     * Minutes past midnight from a timetable cell: "08:59:00", or "16:30a" with a footnote.
     * Null for "via", where no time is published.
     *
     * The last leg's arrival used to be sent as the cell text alone, with its minutes null,
     * so every journey with a change said "time not published" at the destination while
     * the same trip, opened, showed Kalk Bay at 08:59.
     */
    static Integer minutesOf(String raw) {
        if (raw == null) {
            return null;
        }
        java.util.regex.Matcher m = CLOCK.matcher(raw.trim());
        return m.find() ? Integer.parseInt(m.group(1)) * 60 + Integer.parseInt(m.group(2)) : null;
    }

    /** How MyCiTi fares are priced: by band, from the distance along the route. */
    private static final String MYCITI = "myciti_distance";

    /**
     * MyCiTi's distance bands, as {upper km, peak, saver} in cents. The same numbers as
     * BANDS in src/myciti_scraper/fares.py, which fills journey_fare; change both together.
     */
    private static final int[][] MYCITI_BANDS = {
        {5, 1950, 1500}, {10, 2550, 1950}, {20, 3250, 2550}, {30, 3450, 2950},
        {40, 3750, 3200}, {50, 4250, 3850}, {60, 4850, 4350}, {Integer.MAX_VALUE, 5250, 4600},
    };

    /** {peak, saver} for a distance along MyCiTi's routes. */
    static int[] mycitiBand(double km) {
        for (int[] b : MYCITI_BANDS) {
            if (km <= b[0]) {
                return new int[] { b[1], b[2] };
            }
        }
        throw new IllegalStateException("the last band has no upper bound");
    }

    static String mycitiBandLabel(double km) {
        int lower = 0;
        for (int[] b : MYCITI_BANDS) {
            if (b[0] == Integer.MAX_VALUE) {
                return lower + "km+";
            }
            if (km <= b[0]) {
                return lower + "-" + b[0] + "km";
            }
            lower = b[0];
        }
        throw new IllegalStateException("the last band has no upper bound");
    }

    /** How Metrorail fares are priced: by zone, from the distance between two stations. */
    private static final String PRASA_ZONE = "prasa_zone";

    /**
     * PRASA's distance bands, as {upper km, zone, single, weekly Mon-Fri, monthly} in cents.
     * The same numbers as ZONES in src/prasa_scraper/fares.py, which fills journey_fare;
     * change both together.
     */
    private static final int[][] PRASA_BANDS = {
        {15, 1, 1000, 6000, 18000},
        {40, 2, 1200, 7000, 22000},
        {60, 3, 1400, 8000, 25000},
        {Integer.MAX_VALUE, 4, 1500, 9000, 28000},
    };

    /** {zone, single, weekly, monthly} for a distance by rail. */
    static int[] prasaBand(double km) {
        for (int[] b : PRASA_BANDS) {
            if (km <= b[0]) {
                return new int[] { b[1], b[2], b[3], b[4] };
            }
        }
        throw new IllegalStateException("the last band has no upper bound");
    }

    /** How many changes of bus a published transfer allowance covers. */
    private static final Map<String, Integer> TRANSFERS =
            Map.of("Zero", 0, "One", 1, "Two", 2);

    /**
     * How many changes this fare's transfer allowance covers, where it states one.
     *
     * A fare need not say. 9,273 of the 23,805 in this database - every Metrorail one,
     * priced by distance band, and a good many of Golden Arrow's - leave the column null,
     * and a null cannot be looked up in a Map.of at all: it throws rather than missing.
     * So a journey with a change whose two ends happened to have a through fare of that
     * kind answered 500 and the screen showed nothing, which is how a bus pair 558m away
     * came to look worse than a station 1,359m away.
     *
     * Saying nothing about transfers is not the same as allowing one. A fare that does
     * not cover the change is priced a leg at a time, which is what the rider is charged.
     */
    static int changesCovered(FareDto fare) {
        if (fare == null || fare.transfers() == null) {
            return 0;
        }
        return TRANSFERS.getOrDefault(fare.transfers(), 0);
    }

    /** {@code planner.journey_fare} — the same precomputed table the planner reads. */
    private FareDto fareFor(Integer fromId, Integer toId) {
        if (fromId == null || toId == null) {
            return null;
        }
        List<Object[]> rows = stops.findJourneyFare(fromId, toId);
        if (rows.isEmpty()) {
            return null;
        }
        Object[] r = rows.get(0);
        return new FareDto(
                (String) r[0],
                r[1] == null ? null : ((Number) r[1]).intValue(),
                r[2] == null ? null : ((Number) r[2]).intValue(),
                r[3] == null ? null : ((Number) r[3]).intValue(),
                r[4] == null ? null : ((Number) r[4]).intValue(),
                (String) r[5], (String) r[6], (String) r[7], (String) r[8],
                r[9] != null && (Boolean) r[9],
                r.length > 10 && r[10] != null ? ((Number) r[10]).intValue() : null,
                r.length > 11 ? (String) r[11] : null,
                r.length > 12 && r[12] != null ? ((Number) r[12]).intValue() : null,
                r.length > 13 && r[13] != null ? ((Number) r[13]).intValue() : null,
                r.length > 14 && r[14] != null ? ((Number) r[14]).doubleValue() : null,
                r.length > 15 && r[15] != null ? ((Number) r[15]).intValue() : null,
                r.length > 16 && r[16] != null ? ((Number) r[16]).intValue() : null,
                r.length > 17 && r[17] != null ? ((Number) r[17]).intValue() : null);
    }

    /**
     * What the whole multi-bus journey costs. {@code connections._price_connections}
     *
     * One ticket where the operator publishes a fare between the two ends whose transfer
     * allowance covers the changes this journey makes; otherwise a ticket per bus, added
     * up. A journey with an unpriced leg gets no total at all, because a partial sum
     * shown as a total would understate the trip.
     */
    private ConnectionFareDto priceJourney(Integer fromId, Integer toId,
                                           List<ConnectionLegDto> legs) {
        FareDto through = fareFor(fromId, toId);
        int changes = legs.size() - 1;
        // MyCiTi charges a journey with a change as one fare for its whole distance: the
        // City's calculator prices Table View to Kloof Nek, changing at Civic Centre, as a
        // single 20-30km fare. The legs' distances along the route, added up.
        boolean allMyciti = legs.stream().allMatch(l -> l.fare() != null && MYCITI.equals(l.fare().basis()));
        if (allMyciti && legs.stream().allMatch(l -> l.fare().distanceKm() != null)) {
            double km = legs.stream().mapToDouble(l -> l.fare().distanceKm()).sum();
            int[] band = mycitiBand(km);
            FareDto first = legs.get(0).fare();
            return new ConnectionFareDto("through", 1, null, null, first.weeklyCents(), first.monthlyCents(),
                    null, null, MYCITI, mycitiBandLabel(km),
                    String.format(java.util.Locale.ROOT, "%.1f km along the route", km), false,
                    band[0], first.cashEffectiveFrom(), band[1], first.dayPassCents(), first.threeDayPassCents());
        }
        // A Metrorail ticket is for a journey between two stations, priced by the distance
        // between them, and a change of train on the way does not need another. Its fares
        // record no transfer allowance and no card price, so the rule below never applied
        // and every train-only journey with a change came back with no price at all.
        boolean allTrain = legs.stream().allMatch(l -> l.fare() != null && PRASA_ZONE.equals(l.fare().basis()));
        if (allTrain && through != null && through.cashCents() != null && PRASA_ZONE.equals(through.basis())) {
            return new ConnectionFareDto("through", 1, through.perRideCents(),
                    through.fiveRideCents(), through.weeklyCents(), through.monthlyCents(),
                    through.code(), through.transfers(), through.basis(),
                    through.basisFrom(), through.basisTo(), through.zoneApprox(),
                    through.cashCents(), through.cashEffectiveFrom());
        }
        // Stations on different lines have no precomputed fare between them: the fares job
        // prices pairs on one line by the straight line between them, which across a
        // change cuts the corner through Cape Town and would undercharge. The legs' own
        // distances, added up, follow the railway.
        if (allTrain) {
            double km = 0;
            for (ConnectionLegDto leg : legs) {
                if (leg.fare().distanceKm() == null) {
                    km = -1;
                    break;
                }
                km += leg.fare().distanceKm();
            }
            if (km >= 0) {
                int[] band = prasaBand(km);
                return new ConnectionFareDto("through", 1, null, null, band[2], band[3],
                        "Z" + band[0], null, PRASA_ZONE, "Z" + band[0],
                        String.format(java.util.Locale.ROOT, "%.1f km by rail", km), false,
                        band[1], legs.get(0).fare().cashEffectiveFrom());
            }
        }
        if (through != null && through.perRideCents() != null
                && changesCovered(through) >= changes) {
            return new ConnectionFareDto("through", 1, through.perRideCents(),
                    through.fiveRideCents(), through.weeklyCents(), through.monthlyCents(),
                    through.code(), through.transfers(), through.basis(),
                    through.basisFrom(), through.basisTo(), through.zoneApprox(),
                    through.cashCents(), through.cashEffectiveFrom());
        }
        int total = 0;
        for (ConnectionLegDto leg : legs) {
            if (leg.fare() == null || leg.fare().perRideCents() == null) {
                return null;
            }
            total += leg.fare().perRideCents();
        }
        boolean approx = legs.stream()
                .anyMatch(l -> l.fare() != null && Boolean.TRUE.equals(l.fare().zoneApprox()));
        // The cash total, and only when every leg has one. A journey where two buses
        // publish a cash fare and the third does not has no cash price, the same way it
        // has no card price - a sum missing a leg is not a total.
        Integer cash = sumOver(legs, FareDto::cashCents);
        String cashFrom = legs.stream()
                .map(l -> l.fare() == null ? null : l.fare().cashEffectiveFrom())
                .filter(java.util.Objects::nonNull)
                .findFirst().orElse(null);
        return new ConnectionFareDto("per_leg", legs.size(), total,
                sumOver(legs, FareDto::fiveRideCents),
                sumOver(legs, FareDto::weeklyCents),
                sumOver(legs, FareDto::monthlyCents),
                null, null, "per_leg", null, null, approx,
                cash, cash == null ? null : cashFrom);
    }

    /** A ticket per bus means buying each product once per bus. */
    private static Integer sumOver(List<ConnectionLegDto> legs,
                                   java.util.function.Function<FareDto, Integer> field) {
        int total = 0;
        for (ConnectionLegDto leg : legs) {
            Integer value = leg.fare() == null ? null : field.apply(leg.fare());
            if (value == null) {
                return null;
            }
            total += value;
        }
        return total;
    }

    private ConnectionDto toDto(TwoLegRow r, StopRow from, StopRow to, Map<Integer, StopRow> c) {
        ConnectionLegDto leg1 = new ConnectionLegDto(
                from.getId(), from.getName(), from.getLat(), from.getLon(),
                r.getChangeId(), r.getChangeName(), lat(c, r.getChangeId()), lon(c, r.getChangeId()),
                r.getRoute1(), r.getTtn1(), r.getDepRaw1(), ApiFormat.time(r.getArr1()),
                ApiFormat.minutes(r.getDep1()), ApiFormat.minutes(r.getArr1()),
                r.getSched1(), r.getTrip1(), r.getFromSeq1(), r.getToSeq1(),
                fareFor(from.getId(), r.getChangeId()));

        ConnectionLegDto leg2 = new ConnectionLegDto(
                r.getChangeId(), r.getChangeName(), lat(c, r.getChangeId()), lon(c, r.getChangeId()),
                to.getId(), to.getName(), to.getLat(), to.getLon(),
                r.getRoute2(), r.getTtn2(), ApiFormat.time(r.getDep2()), r.getArrRaw2(),
                ApiFormat.minutes(r.getDep2()), minutesOf(r.getArrRaw2()),
                r.getSched2(), r.getTrip2(), r.getFromSeq2(), r.getToSeq2(),
                fareFor(r.getChangeId(), to.getId()));

        List<ConnectionLegDto> legs = List.of(leg1, leg2);
        return new ConnectionDto(r.getDayType(), List.of(r.getChangeName()),
                legs, r.getWaitMinutes(), r.getTotalMinutes(),
                priceJourney(from.getId(), to.getId(), legs));
    }

    private ConnectionDto toDto(ThreeLegRow r, StopRow from, StopRow to, Map<Integer, StopRow> c) {
        ConnectionLegDto leg1 = new ConnectionLegDto(
                from.getId(), from.getName(), from.getLat(), from.getLon(),
                r.getChangeId(), r.getChangeName(), lat(c, r.getChangeId()), lon(c, r.getChangeId()),
                r.getRoute1(), r.getTtn1(), r.getDepRaw1(), ApiFormat.time(r.getArr1()),
                ApiFormat.minutes(r.getDep1()), ApiFormat.minutes(r.getArr1()),
                r.getSched1(), r.getTrip1(), r.getFromSeq1(), r.getToSeq1(),
                fareFor(from.getId(), r.getChangeId()));

        ConnectionLegDto leg2 = new ConnectionLegDto(
                r.getChangeId(), r.getChangeName(), lat(c, r.getChangeId()), lon(c, r.getChangeId()),
                r.getChange2Id(), r.getChange2Name(), lat(c, r.getChange2Id()), lon(c, r.getChange2Id()),
                r.getRoute2(), r.getTtn2(), ApiFormat.time(r.getDep2()), ApiFormat.time(r.getArr2()),
                ApiFormat.minutes(r.getDep2()), ApiFormat.minutes(r.getArr2()),
                r.getSched2(), r.getTrip2(), r.getFromSeq2(), r.getToSeq2(),
                fareFor(r.getChangeId(), r.getChange2Id()));

        ConnectionLegDto leg3 = new ConnectionLegDto(
                r.getChange2Id(), r.getChange2Name(), lat(c, r.getChange2Id()), lon(c, r.getChange2Id()),
                to.getId(), to.getName(), to.getLat(), to.getLon(),
                r.getRoute3(), r.getTtn3(), ApiFormat.time(r.getDep3()), r.getArrRaw3(),
                ApiFormat.minutes(r.getDep3()), minutesOf(r.getArrRaw3()),
                r.getSched3(), r.getTrip3(), r.getFromSeq3(), r.getToSeq3(),
                fareFor(r.getChange2Id(), to.getId()));

        List<ConnectionLegDto> legs = List.of(leg1, leg2, leg3);
        return new ConnectionDto(r.getDayType(),
                List.of(r.getChangeName(), r.getChange2Name()),
                legs, r.getWaitMinutes(), r.getTotalMinutes(),
                priceJourney(from.getId(), to.getId(), legs));
    }
}
