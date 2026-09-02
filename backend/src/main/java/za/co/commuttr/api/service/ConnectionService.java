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
    private final int maxResults;

    public ConnectionService(StopRepository stops,
                             ConnectionRepository connections,
                             @Value("${commuttr.connections.transfer-buffer-minutes:10}") int bufferMinutes,
                             @Value("${commuttr.connections.max-results:6}") int maxResults) {
        this.stops = stops;
        this.connections = connections;
        this.bufferMinutes = bufferMinutes;
        this.maxResults = maxResults;
    }

    public ConnectionsResponse connections(Integer fromId, Integer toId) {
        StopRow from = stops.findRowById(fromId)
                .orElseThrow(() -> ApiException.notFound("stop not found"));
        StopRow to = stops.findRowById(toId)
                .orElseThrow(() -> ApiException.notFound("stop not found"));

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

    /** How many changes of bus a published transfer allowance covers. */
    private static final Map<String, Integer> TRANSFERS =
            Map.of("Zero", 0, "One", 1, "Two", 2);

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
                r[9] != null && (Boolean) r[9]);
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
        if (through != null && through.perRideCents() != null
                && TRANSFERS.getOrDefault(through.transfers(), 0) >= changes) {
            return new ConnectionFareDto("through", 1, through.perRideCents(),
                    through.fiveRideCents(), through.weeklyCents(), through.monthlyCents(),
                    through.code(), through.transfers(), through.basis(),
                    through.basisFrom(), through.basisTo(), through.zoneApprox());
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
        return new ConnectionFareDto("per_leg", legs.size(), total,
                sumOver(legs, FareDto::fiveRideCents),
                sumOver(legs, FareDto::weeklyCents),
                sumOver(legs, FareDto::monthlyCents),
                null, null, "per_leg", null, null, approx);
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
                ApiFormat.minutes(r.getDep2()), null,
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
                ApiFormat.minutes(r.getDep3()), null,
                r.getSched3(), r.getTrip3(), r.getFromSeq3(), r.getToSeq3(),
                fareFor(r.getChange2Id(), to.getId()));

        List<ConnectionLegDto> legs = List.of(leg1, leg2, leg3);
        return new ConnectionDto(r.getDayType(),
                List.of(r.getChangeName(), r.getChange2Name()),
                legs, r.getWaitMinutes(), r.getTotalMinutes(),
                priceJourney(from.getId(), to.getId(), legs));
    }
}
