package za.co.commuttr.api.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import za.co.commuttr.api.dto.StopDtos.ReachableResponse;
import za.co.commuttr.api.dto.StopDtos.ConnectingStopDto;
import za.co.commuttr.api.dto.StopDtos.ReachableStopDto;
import za.co.commuttr.api.dto.StopDtos.StopDto;
import za.co.commuttr.api.dto.StopDtos.NearestStopDto;
import za.co.commuttr.api.dto.StopDtos.NearestStopsResponse;
import za.co.commuttr.api.dto.StopDtos.StopsResponse;
import za.co.commuttr.api.repo.StopRepository;
import za.co.commuttr.api.repo.StopTimeRepository;
import za.co.commuttr.api.repo.projection.Projections.StopRow;
import za.co.commuttr.api.web.ApiException;

import java.util.List;

/** GET /api/stops and GET /api/stops/{id}/reachable. */
@Service
@Transactional(readOnly = true)
public class StopService {

    private final StopRepository stops;
    private final StopTimeRepository stopTimes;

    public StopService(StopRepository stops, StopTimeRepository stopTimes) {
        this.stops = stops;
        this.stopTimes = stopTimes;
    }

    /** GET /api/stops?q=&limit= — prefix matches first, then alphabetical. */
    public StopsResponse listStops(String q, int limit) {
        List<StopRow> rows = (q == null || q.isEmpty())
                ? stops.listAll(limit)
                : stops.searchByName("%" + q + "%",
                        "%" + q.replace(" ", "") + "%", q + "%", limit);
        return new StopsResponse(rows.stream().map(StopService::toDto).toList());
    }

    /**
     * GET /api/nearest_stops — the nearest stops of one kind to a point, and how far.
     *
     * Asked when the rider has chosen a network that does not come near them. Under Metro
     * Rail, BUH REIN to CAPE TOWN showed a blank screen: there is no station within
     * walking distance of BUH REIN, so the plan held only buses, the chip hid those, and
     * nothing was left to draw. The honest answer is not silence, it is Kraaifontein.
     *
     * A wide radius on purpose. Everything else in the app asks what a rider can walk to;
     * this asks where the nearest one IS, which is only interesting once the answer is
     * further than anybody would walk.
     *
     * By OPERATOR, not by kind. Asked for "the nearest bus stop" under the Golden Arrow
     * chip, this returned MyCiTi stations - Quebec, Lower Kloof, Ludwigs Garden - so the
     * screen said "No bus goes from Upper Long, the nearest stop with one is Lower
     * Kloof", a rider tapped it, and the same sentence came back naming another MyCiTi
     * stop. An endless loop made of suggestions that were never Golden Arrow's.
     */
    public NearestStopsResponse nearest(double lat, double lon, String operator,
                                        double radiusM, int limit) {
        return new NearestStopsResponse(
                stops.findNearestOfOperator(lat, lon, operator, radiusM).stream()
                        .filter(r -> r.getLat() != null && r.getLon() != null)
                        .map(r -> new NearestStopDto(
                                r.getId(), r.getName(), r.getLat(), r.getLon(),
                                r.getOperatorCode() == null ? "gabs" : r.getOperatorCode(),
                                r.getOperatorKind() == null ? "bus" : r.getOperatorKind(),
                                Math.round(GeoUtils.haversineM(lat, lon, r.getLat(), r.getLon()))))
                        .sorted(java.util.Comparator.comparingLong(NearestStopDto::distanceM))
                        .limit(limit)
                        .toList());
    }

    /** GET /api/stops/{stop_id}/reachable — on one bus, plus what one change adds. */
    public ReachableResponse reachable(Integer stopId) {
        StopRow origin = stops.findRowById(stopId)
                .orElseThrow(() -> ApiException.notFound("stop not found"));

        List<ReachableStopDto> reachable = stopTimes.findReachableFromStop(stopId).stream()
                .map(r -> new ReachableStopDto(r.getId(), r.getName(), r.getLat(), r.getLon(),
                        r.getTripCount(), r.getRouteCount(),
                        // Everything loaded before operators existed is Golden Arrow.
                        r.getOperatorCode() == null ? "gabs" : r.getOperatorCode(),
                        r.getOperatorKind() == null ? "bus" : r.getOperatorKind()))
                .toList();

        List<ConnectingStopDto> connecting = stopTimes.findConnectingFromStop(stopId).stream()
                .map(r -> new ConnectingStopDto(((Number) r[0]).intValue(), (String) r[1],
                        r[2] == null ? null : ((Number) r[2]).doubleValue(),
                        r[3] == null ? null : ((Number) r[3]).doubleValue(),
                        ((Number) r[4]).longValue()))
                .toList();

        return new ReachableResponse(toDto(origin), reachable, connecting);
    }

    static StopDto toDto(StopRow row) {
        // Everything loaded before operators existed is Golden Arrow.
        return new StopDto(row.getId(), row.getName(), row.getLat(), row.getLon(),
                           row.getOperatorCode() == null ? "gabs" : row.getOperatorCode(),
                           row.getOperatorKind() == null ? "bus" : row.getOperatorKind());
    }
}
