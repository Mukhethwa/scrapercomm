package za.co.commuttr.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import za.co.commuttr.api.dto.StopDtos.StopDto;

import java.util.List;

/**
 * GET /api/connections — journeys that need a change of bus.
 *
 * <p>Only consulted when no direct bus exists, so the client can say "there is no direct
 * bus, but you can get there by changing at X".
 */
public final class ConnectionDtos {

    private ConnectionDtos() { }

    /**
     * One bus ride within a connection. Carries the same identifiers a direct journey
     * does, so a leg can be opened for its stop-by-stop detail and added to the planner
     * exactly like a direct journey.
     *
     * @param arriveRaw the literal timetable cell — "via" where no arrival time is published
     */
    public record ConnectionLegDto(Integer fromStopId,
                                   String fromName,
                                   Double fromLat,
                                   Double fromLon,
                                   Integer toStopId,
                                   String toName,
                                   Double toLat,
                                   Double toLon,
                                   String routeLabel,
                                   String timetableNumber,
                                   String boardRaw,
                                   String arriveRaw,
                                   Integer boardMinutes,
                                   Integer arriveMinutes,
                                   Integer scheduleId,
                                   Integer tripIndex,
                                   Integer fromSeq,
                                   Integer toSeq) { }

    /**
     * @param waitMinutes  total time spent waiting at interchanges
     * @param totalMinutes door-to-door, or null when the final arrival is not published
     */
    public record ConnectionDto(String dayType,
                                List<String> changeAt,
                                List<ConnectionLegDto> legs,
                                Integer waitMinutes,
                                Integer totalMinutes) { }

    /**
     * @param legsRequired how many buses the best answer needs, or null if none was found
     */
    public record ConnectionsResponse(@JsonProperty("from") StopDto from,
                                      @JsonProperty("to") StopDto to,
                                      Integer legsRequired,
                                      List<ConnectionDto> connections) { }
}
