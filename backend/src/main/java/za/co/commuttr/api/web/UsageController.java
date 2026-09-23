package za.co.commuttr.api.web;

import com.fasterxml.jackson.annotation.JsonProperty;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import za.co.commuttr.api.analytics.PlaceSearchEvent;
import za.co.commuttr.api.analytics.SearchAnalyticsEvent;
import za.co.commuttr.api.service.EndpointRef;

/**
 * What the app knows and the server cannot see.
 *
 * <p>Two things never reached us. A commuter who checks the same trip every morning is
 * answered from the copy saved on their phone, so the server saw the first search and
 * nothing after it - which understates exactly the trips people actually make. And stop
 * and place search runs against the stop list on the phone, so what somebody typed, and
 * whether they found anything, was never knowable.
 *
 * <p>Both are sent here after the fact, and only when the rider has left sharing on.
 * Nothing that identifies a person is accepted: an anonymous id the app made, what was
 * typed, and how many results came back.
 */
@RestController
@RequestMapping("/api")
public class UsageController {

    /** Long enough for a place, short enough that nothing else fits. */
    private static final int MAX_QUERY = 40;

    private final ApplicationEventPublisher events;

    public UsageController(ApplicationEventPublisher events) {
        this.events = events;
    }

    /**
     * @param kind "cached_search" for a trip the app answered from its own saved copy,
     *             "place_search" for a search of the stop list on the phone
     */
    public record UsageRequest(String kind,
                               @JsonProperty("from") Integer fromStopId,
                               @JsonProperty("from_lat") Double fromLat,
                               @JsonProperty("from_lon") Double fromLon,
                               @JsonProperty("to") Integer toStopId,
                               @JsonProperty("to_lat") Double toLat,
                               @JsonProperty("to_lon") Double toLon,
                               String endpoint,
                               String query,
                               @JsonProperty("result_count") Integer resultCount,
                               @JsonProperty("chosen_stop_id") Integer chosenStopId) { }

    @PostMapping("/usage")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public void record(@RequestBody UsageRequest body) {
        if (body == null || body.kind() == null) {
            return;
        }
        switch (body.kind()) {
            case "cached_search" -> events.publishEvent(SearchAnalyticsEvent.cached(
                    body.endpoint() == null ? "/api/plan" : body.endpoint(),
                    EndpointRef.of(body.fromStopId(), body.fromLat(), body.fromLon()),
                    EndpointRef.of(body.toStopId(), body.toLat(), body.toLon()),
                    body.resultCount() == null ? 0 : body.resultCount()));
            case "place_search" -> {
                String query = body.query() == null ? "" : body.query().trim();
                if (query.length() < 2) {
                    return;  // A single letter is a keystroke, not a search.
                }
                events.publishEvent(PlaceSearchEvent.of(
                        query.length() > MAX_QUERY ? query.substring(0, MAX_QUERY) : query,
                        body.resultCount() == null ? 0 : body.resultCount(),
                        body.chosenStopId()));
            }
            default -> { }  // An unknown kind is ignored, never an error a rider can see.
        }
    }
}
