package za.co.commuttr.api.web;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionsResponse;
import za.co.commuttr.api.dto.JourneyDtos.JourneysResponse;
import za.co.commuttr.api.dto.PlanDtos.GeocodeResponse;
import za.co.commuttr.api.dto.PlanDtos.LocateResponse;
import za.co.commuttr.api.dto.PlanDtos.NearbyOriginsResponse;
import za.co.commuttr.api.dto.PlanDtos.PlanResponse;
import za.co.commuttr.api.dto.PlanDtos.TripStopsResponse;
import za.co.commuttr.api.service.EndpointRef;
import za.co.commuttr.api.service.ConnectionService;
import za.co.commuttr.api.service.GeocodeService;
import za.co.commuttr.api.service.JourneyService;
import za.co.commuttr.api.service.PlannerService;

/**
 * Journey planning. {@code /api/journeys} plans between two named stops;
 * {@code /api/plan} additionally accepts pins, so an origin or destination can be any
 * point the bus drives past.
 */
@RestController
@RequestMapping("/api")
public class PlannerController {

    private final JourneyService journeyService;
    private final PlannerService planner;
    private final GeocodeService geocodeService;
    private final ConnectionService connectionService;

    public PlannerController(JourneyService journeyService,
                             PlannerService planner,
                             GeocodeService geocodeService,
                             ConnectionService connectionService) {
        this.journeyService = journeyService;
        this.planner = planner;
        this.geocodeService = geocodeService;
        this.connectionService = connectionService;
    }

    /** Direct single-bus journeys, grouped by connecting schedule. */
    @GetMapping("/journeys")
    public JourneysResponse journeys(@RequestParam("from") Integer from,
                                     @RequestParam("to") Integer to) {
        return journeyService.journeys(from, to);
    }

    /**
     * The pin-aware planner. Each endpoint is given either as a stop id
     * ({@code from}/{@code to}) or as a coordinate pair
     * ({@code from_lat}/{@code from_lon}, {@code to_lat}/{@code to_lon}).
     */
    @GetMapping("/plan")
    public PlanResponse plan(@RequestParam(name = "from", required = false) Integer from,
                             @RequestParam(name = "from_lat", required = false) Double fromLat,
                             @RequestParam(name = "from_lon", required = false) Double fromLon,
                             @RequestParam(name = "to", required = false) Integer to,
                             @RequestParam(name = "to_lat", required = false) Double toLat,
                             @RequestParam(name = "to_lon", required = false) Double toLon) {
        EndpointRef fromEp = EndpointRef.of(from, fromLat, fromLon);
        EndpointRef toEp = EndpointRef.of(to, toLat, toLon);
        if (fromEp == null || toEp == null) {
            throw PlannerService.missingEndpoints();
        }
        return planner.plan(fromEp, toEp);
    }

    /**
     * How to get there when no single service does it: two legs if possible, three if not.
     * Consulted after /api/plan comes back empty.
     *
     * A stop id, or a point. A point was refused until now, so a rider who searched a
     * place rather than a stop was told a journey with a change could not be worked out -
     * which is a statement about this endpoint, not about the network. They walk to a
     * stop like anybody else.
     */
    @GetMapping("/connections")
    public ConnectionsResponse connections(
            @RequestParam(value = "from", required = false) Integer from,
            @RequestParam(value = "from_lat", required = false) Double fromLat,
            @RequestParam(value = "from_lon", required = false) Double fromLon,
            @RequestParam(value = "to", required = false) Integer to,
            @RequestParam(value = "to_lat", required = false) Double toLat,
            @RequestParam(value = "to_lon", required = false) Double toLon) {
        return connectionService.connections(from, fromLat, fromLon, to, toLat, toLon);
    }

    /** Legs whose real road path passes near a point. */
    @GetMapping("/locate")
    public LocateResponse locate(@RequestParam double lat, @RequestParam double lon) {
        return planner.locate(lat, lon);
    }

    /**
     * The stops a specific trip actually serves between two sequence positions, with
     * times, for the "where do I get on / off" breakdown.
     */
    @GetMapping("/trip_stops")
    public TripStopsResponse tripStops(@RequestParam("schedule_id") Integer scheduleId,
                                       @RequestParam("trip_index") Integer tripIndex,
                                       @RequestParam("from_seq") Integer fromSeq,
                                       @RequestParam("to_seq") Integer toSeq) {
        return planner.tripStops(scheduleId, tripIndex, fromSeq, toSeq);
    }

    /** Alternative boarding points when the commuter's own stop has no direct bus. */
    @GetMapping("/nearby_origins")
    public NearbyOriginsResponse nearbyOrigins(@RequestParam double lat,
                                               @RequestParam double lon,
                                               @RequestParam("to") Integer to,
                                               @RequestParam(defaultValue = "2500") Integer radius,
                                               @RequestParam(required = false) Integer exclude,
                                               @RequestParam(name = "day_type", required = false) String dayType) {
        return planner.nearbyOrigins(lat, lon, to, radius, exclude, dayType);
    }

    /** Geocode a place/address via OpenStreetMap Nominatim (no key). For pin input. */
    /**
     * @param kind "bus" or "train" to offer only places that network reaches. The search
     *             box passes whatever operator chip the rider has chosen, so the
     *             suggestions and the results can no longer disagree.
     */
    @GetMapping("/geocode")
    public GeocodeResponse geocode(@RequestParam String q,
                                   @RequestParam(required = false) String kind) {
        return geocodeService.geocode(q, kind);
    }
}
