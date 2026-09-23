package za.co.commuttr.api.analytics;

import java.time.OffsetDateTime;

/**
 * Somebody searched the stop list on their phone.
 *
 * <p>What was typed and whether anything was found, which is the half of demand the
 * planner never saw: a place nobody can find is either a gap in the network or a name we
 * spell differently from the people who use it.
 *
 * @param query        what was typed, trimmed to 40 characters
 * @param resultCount  how many stops and places matched
 * @param chosenStopId the stop that was picked, or null when the rider picked nothing
 */
public record PlaceSearchEvent(String query,
                               int resultCount,
                               Integer chosenStopId,
                               String deviceId,
                               String client,
                               OffsetDateTime searchedAt) {

    public static PlaceSearchEvent of(String query, int resultCount, Integer chosenStopId) {
        return new PlaceSearchEvent(query, resultCount, chosenStopId,
                ClientContext.deviceId(), ClientContext.client(), OffsetDateTime.now());
    }
}
