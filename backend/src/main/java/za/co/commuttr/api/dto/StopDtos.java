package za.co.commuttr.api.dto;

import java.util.List;

/** Payloads for /api/stops, /api/stops/{id}/reachable, /api/reachable_point, /api/areas. */
public final class StopDtos {

    private StopDtos() { }

    /** A named stop as every endpoint exposes it. */
    /**
     * A stop, and who serves it.
     *
     * The operator is not decoration: stops are unique per operator, so RETREAT the
     * station and RETREAT the bus stop are two rows with the same name, and a search
     * that does not say which is which offers a rider a coin toss.
     */
    public record StopDto(Integer id, String name, Double lat, Double lon,
                          String operatorCode, String operatorKind) { }

    public record StopsResponse(List<StopDto> stops) { }

    /** GET /api/stops/{id}/reachable row. */
    public record ReachableStopDto(Integer id,
                                   String name,
                                   Double lat,
                                   Double lon,
                                   Long tripCount,
                                   Long routeCount) { }

    /** GET /api/stops/{id}/reachable row for a destination that needs one change. */
    public record ConnectingStopDto(Integer id,
                                    String name,
                                    Double lat,
                                    Double lon,
                                    Long changeCount) { }

    public record ReachableResponse(StopDto origin,
                                    List<ReachableStopDto> reachable,
                                    List<ConnectingStopDto> connecting) { }

    /**
     * GET /api/reachable_point row. Note this carries only trip_count — the pin planner
     * counts trips as it walks anchors and never computes route_count, exactly as
     * planner.reachable_from did.
     */
    public record DownstreamStopDto(Integer id,
                                    String name,
                                    Double lat,
                                    Double lon,
                                    Integer tripCount) { }

    /** An unnamed lat/lon endpoint: {"kind": "pin", "lat": .., "lon": ..}. */
    public record PinDto(String kind, Double lat, Double lon) {
        public static PinDto of(double lat, double lon) {
            return new PinDto("pin", lat, lon);
        }
    }

    public record ReachablePointResponse(PinDto origin, List<DownstreamStopDto> reachable) { }

    /**
     * @param areas     every area a rider can search
     * @param railAreas the subset with a station in them, so the suggestion can say so.
     *                  Additive rather than a change of shape: an area is still a name.
     */
    public record AreasResponse(List<String> areas, List<String> railAreas) { }

    /**
     * An operator the app can actually plan with.
     *
     * "Can plan with" means it has timetables loaded, not that it is listed somewhere:
     * a filter chip a rider can press that returns nothing is worse than one that is
     * visibly not ready yet.
     */
    public record OperatorDto(String code, String name, String kind,
                              int routes, long departures) { }

    public record OperatorsResponse(List<OperatorDto> operators) { }
}
