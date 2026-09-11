package za.co.commuttr.api.web;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import za.co.commuttr.api.dto.StopDtos.ReachablePointResponse;
import za.co.commuttr.api.dto.StopDtos.ReachableResponse;
import za.co.commuttr.api.dto.StopDtos.NearestStopsResponse;
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

    /**
     * The nearest stops of one kind to a point, however far away they are.
     *
     * @param operator the operator code - "gabs", "myciti", "metrorail". Not a kind:
     *        two bus companies do not share stops, and answering "the nearest bus stop"
     *        under one chip with the other's stations is how a referral came to point at
     *        somewhere the chosen operator does not go.
     * @param radius metres to look within. Wide by default: this is asked when the rider
     *               has chosen a network with nothing near them, so the useful answer is
     *               beyond walking distance by definition.
     */
    @GetMapping("/nearest_stops")
    public NearestStopsResponse nearestStops(@RequestParam double lat,
                                             @RequestParam double lon,
                                             @RequestParam String operator,
                                             @RequestParam(defaultValue = "20000") double radius,
                                             @RequestParam(defaultValue = "3") int limit) {
        return stops.nearest(lat, lon, operator, radius, limit);
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
