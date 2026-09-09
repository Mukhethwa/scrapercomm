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

    /** A footnote letter and what it means, e.g. "b" -> "Fridays". */
    public record TripNoteDto(String code, String description) { }

    public record TripStopsResponse(List<TripStopDto> stops, List<TripNoteDto> notes) { }

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
                                   Integer toSeq,
                                    Integer stopCount) { }

    /** {@code roadPath} is a list of [lat, lon] pairs stitched across the segment. */
    /**
     * What the ride costs, or null where the operator publishes no fare for it.
     *
     * `basis` says where the number came from - "exact" for a fare printed against
     * these two places, "section" for the nearest published fare that still covers the
     * whole ride, "route" for the trip's own end-to-end fare - and basisFrom/basisTo
     * name the places it is printed between, so the app can show its working.
     */
    public record FareDto(String code,
                          Integer perRideCents,
                          Integer fiveRideCents,
                          Integer weeklyCents,
                          Integer monthlyCents,
                          String transfers,
                          String basis,
                          String basisFrom,
                          String basisTo,
                          /** The stop is not itself named on the fare page and was
                           *  priced as part of the surrounding area. */
                          Boolean zoneApprox) { }

    public record PlanOptionDto(String timetableNumber,
                                String routeLabel,
                                /** Who runs this service: 'gabs', 'metrorail'. */
                                String operatorCode,
                                String operatorName,
                                /** 'bus' or 'train'. */
                                String operatorKind,
                                String dayType,
                                String dayLabel,
                                List<PlanSegmentStopDto> segmentStops,
                                List<double[]> roadPath,
                                List<PlanDepartureDto> departures,
                                Boolean boardApprox,
                                Boolean alightApprox,
                                String boardLabel,
                                String alightLabel,
                                /**
                                 * How far the rider walks to the boarding point, in
                                 * metres, or null where they are already on it.
                                 *
                                 * "Board at KRAAIFONTEIN" is an instruction only if it
                                 * says how far away Kraaifontein station is. It is 1,834m
                                 * from the high school somebody might have searched, which
                                 * is a normal walk to a train and a thing worth being told
                                 * before you set out rather than after.
                                 */
                                Long boardAwayM,
                                Long alightAwayM,
                                FareDto fare) { }

    /** from/to is a StopDto for a named stop, or a PinDto for a lat/lon pin. */
    public record PlanResponse(@JsonProperty("from") Object from,
                               @JsonProperty("to") Object to,
                               List<PlanOptionDto> options) { }

    /** GET /api/geocode row (OpenStreetMap Nominatim). */
    public record GeoHitDto(String name, String full, Double lat, Double lon) { }

    public record GeocodeResponse(List<GeoHitDto> results) { }
}
