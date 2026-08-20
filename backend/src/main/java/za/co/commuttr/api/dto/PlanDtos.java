package za.co.commuttr.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Payloads for the pin-aware planner: /api/plan, /api/locate, /api/trip_stops,
 * /api/nearby_origins.
 */
public final class PlanDtos {

    private PlanDtos() { }

    /** GET /api/locate row: a leg whose road path passes near the point. */
    public record LegHitDto(Integer fromStopId,
                            Integer toStopId,
                            Double distanceM,
                            Double fraction) { }

    public record LocateResponse(Double lat, Double lon, List<LegHitDto> legs) { }

    /** GET /api/trip_stops row. */
    public record TripStopDto(String name,
                              Double lat,
                              Double lon,
                              Integer stopSequence,
                              String rawValue,
                              String cellType,
                              String departureTime) { }

    public record TripStopsResponse(List<TripStopDto> stops) { }

    /** GET /api/nearby_origins row. distanceM is a whole number of metres. */
    public record NearbyOriginDto(Integer id,
                                  String name,
                                  Double lat,
                                  Double lon,
                                  Long distanceM,
                                  Long tripCount,
                                  String earliest) { }

    public record NearbyOriginsResponse(List<NearbyOriginDto> origins) { }

    public record PlanSegmentStopDto(Integer stopId,
                                     String name,
                                     Double lat,
                                     Double lon,
                                     Integer stopSequence) { }

    /**
     * A single boardable departure. {@code boardMinutes}/{@code arriveMinutes} are
     * {@link Number} so an exact stop stays an integer (477) while an interpolated pin
     * stays fractional (477.35), matching the Python output byte for byte.
     */
    public record PlanDepartureDto(String boardRaw,
                                   Boolean boardApprox,
                                   Number boardMinutes,
                                   String arriveRaw,
                                   Boolean arriveApprox,
                                   Number arriveMinutes,
                                   Integer scheduleId,
                                   Integer tripIndex,
                                   Integer fromSeq,
                                   Integer toSeq) { }

    /** {@code roadPath} is a list of [lat, lon] pairs stitched across the segment. */
    public record PlanOptionDto(String timetableNumber,
                                String routeLabel,
                                String dayType,
                                String dayLabel,
                                List<PlanSegmentStopDto> segmentStops,
                                List<double[]> roadPath,
                                List<PlanDepartureDto> departures,
                                Boolean boardApprox,
                                Boolean alightApprox,
                                String boardLabel,
                                String alightLabel) { }

    /** from/to is a StopDto for a named stop, or a PinDto for a lat/lon pin. */
    public record PlanResponse(@JsonProperty("from") Object from,
                               @JsonProperty("to") Object to,
                               List<PlanOptionDto> options) { }

    /** GET /api/geocode row (OpenStreetMap Nominatim). */
    public record GeoHitDto(String name, String full, Double lat, Double lon) { }

    public record GeocodeResponse(List<GeoHitDto> results) { }
}
