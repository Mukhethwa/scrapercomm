package za.co.commuttr.api.analytics;

import za.co.commuttr.api.service.EndpointRef;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * Published the moment a journey search has produced its options, before the response is
 * serialised. Carries everything the analytics rows need so the listener never has to
 * touch the request thread's state (or its transaction).
 *
 * @param endpoint   the API path that served the search, e.g. {@code /api/plan}
 * @param from       the origin the commuter asked for
 * @param to         the destination the commuter asked for
 * @param options    the journey options returned — recorded individually so route demand
 *                   is measurable, not just how many results came back
 * @param durationMs wall-clock time spent resolving the journey
 * @param searchedAt when the search happened
 */
public record SearchAnalyticsEvent(String endpoint,
                                   EndpointRef from,
                                   EndpointRef to,
                                   List<OptionSummary> options,
                                   long durationMs,
                                   OffsetDateTime searchedAt) {

    /**
     * One returned option, reduced to what identifies the physical service. Both
     * {@code /api/plan} and {@code /api/journeys} options map onto this shape.
     */
    public record OptionSummary(String timetableNumber,
                                String routeLabel,
                                String dayType,
                                int departureCount) { }

    public SearchAnalyticsEvent {
        options = options == null ? List.of() : List.copyOf(options);
    }

    /** How many options the search returned. */
    public int optionCount() {
        return options.size();
    }

    public static SearchAnalyticsEvent of(String endpoint, EndpointRef from, EndpointRef to,
                                          List<OptionSummary> options, long durationMs) {
        return new SearchAnalyticsEvent(endpoint, from, to, options, durationMs,
                OffsetDateTime.now());
    }
}
