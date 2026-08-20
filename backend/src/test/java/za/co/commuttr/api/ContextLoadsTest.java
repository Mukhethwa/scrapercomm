package za.co.commuttr.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.TestPropertySource;
import za.co.commuttr.api.analytics.SearchAnalyticsListener;
import za.co.commuttr.api.repo.LegGeometryRepository;
import za.co.commuttr.api.repo.RouteRepository;
import za.co.commuttr.api.repo.ScheduleRepository;
import za.co.commuttr.api.repo.SearchAnalyticsRepository;
import za.co.commuttr.api.repo.StopTimeRepository;
import za.co.commuttr.api.service.PlannerService;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Boots the whole application without a live database.
 *
 * <p>This is the cheap guard against the mistakes that only surface at startup: a
 * mistyped {@code @Column}, an unparseable JPQL query, a derived finder naming a
 * property that does not exist, or a bean that cannot be wired. It cannot exercise the
 * native SQL — run the API against the real database for that.
 */
@SpringBootTest
@TestPropertySource(properties = {
        // Pin the dialect and forbid metadata probing so Hibernate never dials out.
        "spring.jpa.database-platform=org.hibernate.dialect.PostgreSQLDialect",
        "spring.jpa.properties.hibernate.boot.allow_jdbc_metadata_access=false",
        "spring.datasource.hikari.initialization-fail-timeout=-1",
        "spring.datasource.hikari.connection-timeout=250",
        "spring.sql.init.mode=never",
        "spring.jpa.hibernate.ddl-auto=none",
})
class ContextLoadsTest {

    @Autowired ApplicationContext context;
    @Autowired RouteRepository routes;
    @Autowired ScheduleRepository schedules;
    @Autowired StopTimeRepository stopTimes;
    @Autowired LegGeometryRepository legGeometry;
    @Autowired SearchAnalyticsRepository analytics;
    @Autowired PlannerService planner;
    @Autowired SearchAnalyticsListener listener;

    @Test
    void everyRepositoryAndServiceIsWired() {
        assertThat(routes).isNotNull();
        assertThat(schedules).isNotNull();
        assertThat(stopTimes).isNotNull();
        assertThat(legGeometry).isNotNull();
        assertThat(analytics).isNotNull();
        assertThat(planner).isNotNull();
        assertThat(listener).isNotNull();
    }

    @Test
    void theStranglerFigFallbackIsOffByDefault() {
        assertThat(context.getBeanNamesForType(
                za.co.commuttr.api.config.LegacyFallbackFilter.class)).isEmpty();
    }
}
