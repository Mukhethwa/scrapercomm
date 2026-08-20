package za.co.commuttr.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import za.co.commuttr.api.dto.StopDtos.StopDto;

import java.util.List;

/** Payloads for GET /api/journeys (direct single-bus journeys between two named stops). */
public final class JourneyDtos {

    private JourneyDtos() { }

    /** Times are "HH:MM" or null; raw values are the literal PDF cell text. */
    public record JourneyDepartureDto(String boardTime,
                                      String boardRaw,
                                      String boardType,
                                      String noteCode,
                                      String arriveTime,
                                      String arriveRaw,
                                      String arriveType) { }

    public record SegmentStopDto(String name, Double lat, Double lon, Integer stopSequence) { }

    public record JourneyOptionDto(String timetableNumber,
                                   String routeLabel,
                                   String dayType,
                                   String dayLabel,
                                   List<Integer> timetableIds,
                                   List<SegmentStopDto> segmentStops,
                                   List<JourneyDepartureDto> departures) { }

    /** "from"/"to" are explicit so the naming strategy leaves them alone. */
    public record JourneysResponse(@JsonProperty("from") StopDto from,
                                   @JsonProperty("to") StopDto to,
                                   List<JourneyOptionDto> options) { }
}
