package za.co.commuttr.api.web;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import za.co.commuttr.api.dto.StopDtos.ReachablePointResponse;
import za.co.commuttr.api.dto.StopDtos.ReachableResponse;
import za.co.commuttr.api.dto.StopDtos.StopsResponse;
import za.co.commuttr.api.service.PlannerService;
import za.co.commuttr.api.service.StopService;

/** Stop search and single-bus reachability, for both named stops and dropped pins. */
@RestController
@RequestMapping("/api")
public class StopController {

    private final StopService stops;
    private final PlannerService planner;

    public StopController(StopService stops, PlannerService planner) {
        this.stops = stops;
        this.planner = planner;
    }

    @GetMapping("/stops")
    public StopsResponse listStops(@RequestParam(required = false) String q,
                                   @RequestParam(defaultValue = "20") int limit) {
        return stops.listStops(q, limit);
    }

    /** Stops reachable from this one on a SINGLE bus (a trip serves both, in order). */
    @GetMapping("/stops/{stopId}/reachable")
    public ReachableResponse reachable(@PathVariable Integer stopId) {
        return stops.reachable(stopId);
    }

    /** The same question for a pin rather than a named stop. */
    @GetMapping("/reachable_point")
    public ReachablePointResponse reachablePoint(@RequestParam double lat,
                                                 @RequestParam double lon) {
        return planner.reachablePoint(lat, lon);
    }
}
