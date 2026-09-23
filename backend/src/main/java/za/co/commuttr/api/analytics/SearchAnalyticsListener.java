package za.co.commuttr.api.analytics;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import za.co.commuttr.api.domain.SearchAnalytics;
import za.co.commuttr.api.domain.SearchAnalyticsOption;
import za.co.commuttr.api.domain.AppError;
import za.co.commuttr.api.domain.PlaceSearch;
import za.co.commuttr.api.repo.AppErrorRepository;
import za.co.commuttr.api.repo.PlaceSearchRepository;
import za.co.commuttr.api.repo.SearchAnalyticsOptionRepository;
import za.co.commuttr.api.repo.SearchAnalyticsRepository;
import za.co.commuttr.api.service.EndpointRef;

import java.util.List;

/**
 * Writes the search_analytics rows off the request thread.
 *
 * <p>{@code @Async} hands the work to the application task executor, which (with
 * {@code spring.threads.virtual.enabled=true}) is virtual-thread backed — so the
 * blocking INSERTs park a virtual thread instead of occupying a platform one, and the
 * planner response goes out without waiting for the database round trip.
 *
 * <p>Analytics is strictly best-effort: every failure is logged and swallowed so a
 * broken or missing analytics table can never affect a commuter's journey search.
 */
@Component
public class SearchAnalyticsListener {

    private static final Logger log = LoggerFactory.getLogger(SearchAnalyticsListener.class);

    private final SearchAnalyticsRepository searches;
    private final SearchAnalyticsOptionRepository options;
    private final PlaceSearchRepository placeSearches;
    private final AppErrorRepository appErrors;
    private final boolean enabled;

    public SearchAnalyticsListener(SearchAnalyticsRepository searches,
                                   SearchAnalyticsOptionRepository options,
                                   PlaceSearchRepository placeSearches,
                                   AppErrorRepository appErrors,
                                   @Value("${commuttr.analytics.enabled:true}") boolean enabled) {
        this.searches = searches;
        this.options = options;
        this.placeSearches = placeSearches;
        this.appErrors = appErrors;
        this.enabled = enabled;
    }

    /**
     * A crash the app could not handle.
     *
     * <p>Recorded even when analytics is switched off on the server: knowing the app is
     * broken is not the same kind of thing as counting how it is used, and a build that
     * crashes for everybody is worth hearing about however the operator has configured
     * their counting.
     */
    @Async
    @EventListener
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void onAppError(AppErrorEvent event) {
        try {
            appErrors.save(new AppError(event.deviceId(), event.client(), event.appVersion(),
                    event.platform(), event.kind(), event.message(), event.where(),
                    event.happenedAt()));
            log.warn("App error reported ({} {}): {}", event.platform(), event.appVersion(),
                    event.message());
        } catch (RuntimeException ex) {
            log.warn("Could not record an app error: {}", ex.toString());
        }
    }

    /** Same rules as a journey search: off the request thread, and never fatal. */
    @Async
    @EventListener
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void onPlaceSearch(PlaceSearchEvent event) {
        if (!enabled) {
            return;
        }
        try {
            placeSearches.save(new PlaceSearch(event.deviceId(), event.client(), event.query(),
                    event.resultCount(), event.chosenStopId(), event.searchedAt()));
        } catch (RuntimeException ex) {
            log.warn("Could not record a place search: {}", ex.toString());
        }
    }

    @Async
    @EventListener
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void onSearch(SearchAnalyticsEvent event) {
        if (!enabled) {
            return;
        }
        try {
            EndpointRef from = event.from();
            EndpointRef to = event.to();

            SearchAnalytics search = searches.save(new SearchAnalytics(
                    event.endpoint(),
                    from == null ? null : from.kind(),
                    from == null ? null : from.stopId(),
                    from == null ? null : from.lat(),
                    from == null ? null : from.lon(),
                    to == null ? null : to.kind(),
                    to == null ? null : to.stopId(),
                    to == null ? null : to.lat(),
                    to == null ? null : to.lon(),
                    event.optionCount(),
                    event.durationMs(),
                    event.searchedAt(),
                    event.deviceId(),
                    event.client(),
                    event.cached()));

            // One row per option, so "which routes are people searching for" is a
            // GROUP BY rather than a question the data cannot answer.
            List<SearchAnalyticsOption> rows = event.options().stream()
                    .map(o -> new SearchAnalyticsOption(search.getId(), o.timetableNumber(),
                            o.routeLabel(), o.dayType(), o.departureCount()))
                    .toList();
            if (!rows.isEmpty()) {
                options.saveAll(rows);
            }
        } catch (RuntimeException ex) {
            log.warn("Could not record search analytics for {} ({} options): {}",
                    event.endpoint(), event.optionCount(), ex.toString());
        }
    }
}
