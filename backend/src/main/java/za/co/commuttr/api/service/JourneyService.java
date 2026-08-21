package za.co.commuttr.api.service;

import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import za.co.commuttr.api.analytics.SearchAnalyticsEvent;
import za.co.commuttr.api.dto.JourneyDtos.JourneyDepartureDto;
import za.co.commuttr.api.dto.JourneyDtos.JourneyOptionDto;
import za.co.commuttr.api.dto.JourneyDtos.JourneysResponse;
import za.co.commuttr.api.dto.JourneyDtos.SegmentStopDto;
import za.co.commuttr.api.repo.ScheduleStopRepository;
import za.co.commuttr.api.repo.StopRepository;
import za.co.commuttr.api.repo.StopTimeRepository;
import za.co.commuttr.api.repo.projection.Projections.JourneyConnRow;
import za.co.commuttr.api.repo.projection.Projections.JourneyDepartureRow;
import za.co.commuttr.api.repo.projection.Projections.StopRow;
import za.co.commuttr.api.web.ApiException;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * GET /api/journeys — direct single-bus journeys between two named stops, grouped by
 * physical service. Ported from {@code api.journeys}.
 */
@Service
@Transactional(readOnly = true)
public class JourneyService {

    private final StopRepository stops;
    private final StopTimeRepository stopTimes;
    private final ScheduleStopRepository scheduleStops;
    private final ApplicationEventPublisher events;

    public JourneyService(StopRepository stops,
                          StopTimeRepository stopTimes,
                          ScheduleStopRepository scheduleStops,
                          ApplicationEventPublisher events) {
        this.stops = stops;
        this.stopTimes = stopTimes;
        this.scheduleStops = scheduleStops;
        this.events = events;
    }

    /**
     * The same physical service is listed by the site under several origin/destination
     * route names, so departures are merged on (timetable number, direction, day type).
     */
    private record GroupKey(String timetableNumber, String directionLabel, String dayType) { }

    private static final class Group {
        String timetableNumber;
        String routeLabel;
        String dayType;
        String dayLabel;
        final Set<Integer> timetableIds = new LinkedHashSet<>();
        List<SegmentStopDto> segmentStops;
        final List<JourneyDepartureDto> departures = new ArrayList<>();
        final Set<List<String>> seen = new HashSet<>();
    }

    public JourneysResponse journeys(Integer from, Integer to) {
        long startedAt = System.nanoTime();

        Map<Integer, StopRow> found = new LinkedHashMap<>();
        for (StopRow row : stops.findRowsByIds(List.of(from, to))) {
            found.put(row.getId(), row);
        }
        if (!found.containsKey(from) || !found.containsKey(to)) {
            throw ApiException.notFound("stop not found");
        }

        List<JourneyConnRow> connections = stopTimes.findConnectingSchedules(from, to);

        Map<GroupKey, Group> groups = new LinkedHashMap<>();
        for (JourneyConnRow c : connections) {
            GroupKey key = new GroupKey(c.getTimetableNumber(), c.getDirectionLabel(), c.getDayType());
            Group g = groups.get(key);
            if (g == null) {
                g = new Group();
                g.timetableNumber = c.getTimetableNumber();
                g.routeLabel = c.getDirectionLabel(); // the actual bus path
                g.dayType = c.getDayType();
                g.dayLabel = c.getDayLabel();
                g.segmentStops = scheduleStops
                        .findSegment(c.getScheduleId(), c.getBseq(), c.getAseq()).stream()
                        .map(s -> new SegmentStopDto(s.getName(), s.getLat(), s.getLon(),
                                s.getStopSequence()))
                        .toList();
                groups.put(key, g);
            }
            g.timetableIds.add(c.getTimetableId());

            for (JourneyDepartureRow d : stopTimes.findDepartures(c.getSsx(), c.getSsy(), c.getScheduleId())) {
                // Dedup across timetable versions on the literal PDF cell text.
                List<String> signature = Arrays.asList(d.getBoardRaw(), d.getArriveRaw());
                if (!g.seen.add(signature)) {
                    continue;
                }
                g.departures.add(new JourneyDepartureDto(
                        ApiFormat.time(d.getBoardTime()),
                        d.getBoardRaw(),
                        d.getBoardType(),
                        d.getNoteCode(),
                        ApiFormat.time(d.getArriveTime()),
                        d.getArriveRaw(),
                        d.getArriveType()));
            }
        }

        List<JourneyOptionDto> options = new ArrayList<>(groups.size());
        for (Group g : groups.values()) {
            g.departures.sort(departureOrder());
            options.add(new JourneyOptionDto(
                    g.timetableNumber,
                    g.routeLabel,
                    g.dayType,
                    g.dayLabel,
                    g.timetableIds.stream().sorted().toList(),
                    g.segmentStops,
                    List.copyOf(g.departures)));
        }
        options.sort(optionOrder());

        events.publishEvent(SearchAnalyticsEvent.of(
                "/api/journeys",
                EndpointRef.stop(from),
                EndpointRef.stop(to),
                options.stream()
                        .map(o -> new SearchAnalyticsEvent.OptionSummary(
                                o.timetableNumber(), o.routeLabel(), o.dayType(),
                                o.departures().size()))
                        .toList(),
                (System.nanoTime() - startedAt) / 1_000_000));

        return new JourneysResponse(StopService.toDto(found.get(from)),
                StopService.toDto(found.get(to)), options);
    }

    /** Timed departures first, then by board time, then by arrival time. */
    private static Comparator<JourneyDepartureDto> departureOrder() {
        return Comparator
                .comparing((JourneyDepartureDto d) -> d.boardTime() == null)
                .thenComparing(d -> d.boardTime() == null ? "" : d.boardTime())
                .thenComparing(d -> d.arriveTime() == null ? "" : d.arriveTime());
    }

    /** Weekday, Saturday, Sunday, public holiday, then anything else; ties by label. */
    static Comparator<JourneyOptionDto> optionOrder() {
        return Comparator
                .comparingInt((JourneyOptionDto o) -> DayTypes.order(o.dayType()))
                .thenComparing(JourneyOptionDto::routeLabel,
                        Comparator.nullsFirst(Comparator.naturalOrder()));
    }
}
