package za.co.commuttr.api.dto;

import java.util.List;

/** Payloads for /api/stops, /api/stops/{id}/reachable, /api/reachable_point, /api/areas. */
public final class StopDtos {

    private StopDtos() { }

    /** A named stop as every endpoint exposes it. */
    public record StopDto(Integer id, String name, Double lat, Double lon) { }

    public record StopsResponse(List<StopDto> stops) { }

    /** GET /api/stops/{id}/reachable row. */
    public record ReachableStopDto(Integer id,
                                   String name,
                                   Double lat,
                                   Double lon,
                                   Long tripCount,
                                   Long routeCount) { }

    public record ReachableResponse(StopDto origin, List<ReachableStopDto> reachable) { }

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

    public record AreasResponse(List<String> areas) { }
}
