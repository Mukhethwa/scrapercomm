package za.co.commuttr.api.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import za.co.commuttr.api.dto.StopDtos.ReachableResponse;
import za.co.commuttr.api.dto.StopDtos.ReachableStopDto;
import za.co.commuttr.api.dto.StopDtos.StopDto;
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
                : stops.searchByName("%" + q + "%", q + "%", limit);
        return new StopsResponse(rows.stream().map(StopService::toDto).toList());
    }

    /** GET /api/stops/{stop_id}/reachable — stops reachable on a SINGLE bus. */
    public ReachableResponse reachable(Integer stopId) {
        StopRow origin = stops.findRowById(stopId)
                .orElseThrow(() -> ApiException.notFound("stop not found"));

        List<ReachableStopDto> reachable = stopTimes.findReachableFromStop(stopId).stream()
                .map(r -> new ReachableStopDto(r.getId(), r.getName(), r.getLat(), r.getLon(),
                        r.getTripCount(), r.getRouteCount()))
                .toList();

        return new ReachableResponse(toDto(origin), reachable);
    }

    static StopDto toDto(StopRow row) {
        return new StopDto(row.getId(), row.getName(), row.getLat(), row.getLon());
    }
}
