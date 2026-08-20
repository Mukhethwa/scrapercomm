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
import za.co.commuttr.api.repo.SearchAnalyticsRepository;
import za.co.commuttr.api.service.EndpointRef;

/**
 * Writes the search_analytics row off the request thread.
 *
 * <p>{@code @Async} hands the work to the application task executor, which (with
 * {@code spring.threads.virtual.enabled=true}) is virtual-thread backed — so the
 * blocking INSERT parks a virtual thread instead of occupying a platform one, and the
 * planner response goes out without waiting for the database round trip.
 *
 * <p>Analytics is strictly best-effort: every failure is logged and swallowed so a
 * broken or missing analytics table can never affect a commuter's journey search.
 */
@Component
public class SearchAnalyticsListener {

    private static final Logger log = LoggerFactory.getLogger(SearchAnalyticsListener.class);

    private final SearchAnalyticsRepository repository;
    private final boolean enabled;

    public SearchAnalyticsListener(SearchAnalyticsRepository repository,
                                   @Value("${commuttr.analytics.enabled:true}") boolean enabled) {
        this.repository = repository;
        this.enabled = enabled;
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
            repository.save(new SearchAnalytics(
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
                    event.searchedAt()));
        } catch (RuntimeException ex) {
            log.warn("Could not record search analytics for {} ({} options): {}",
                    event.endpoint(), event.optionCount(), ex.toString());
        }
    }
}
