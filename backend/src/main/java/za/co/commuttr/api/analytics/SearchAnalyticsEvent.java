package za.co.commuttr.api.analytics;

import za.co.commuttr.api.service.EndpointRef;

import java.time.OffsetDateTime;

/**
 * Published the moment a journey search has produced its options, before the response is
 * serialised. Carries everything the analytics row needs so the listener never has to
 * touch the request thread's state (or its transaction).
 *
 * @param endpoint    the API path that served the search, e.g. {@code /api/plan}
 * @param from        the origin the commuter asked for
 * @param to          the destination the commuter asked for
 * @param optionCount how many journey options were found
 * @param durationMs  wall-clock time spent resolving the journey
 * @param searchedAt  when the search happened
 */
public record SearchAnalyticsEvent(String endpoint,
                                   EndpointRef from,
                                   EndpointRef to,
                                   int optionCount,
                                   long durationMs,
                                   OffsetDateTime searchedAt) {

    public static SearchAnalyticsEvent of(String endpoint, EndpointRef from, EndpointRef to,
                                          int optionCount, long durationMs) {
        return new SearchAnalyticsEvent(endpoint, from, to, optionCount, durationMs,
                OffsetDateTime.now());
    }
}
