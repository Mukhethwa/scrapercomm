package za.co.commuttr.api.analytics;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The id that turns "how many searches" into "how many people".
 *
 * <p>It arrives in a header from the app and is written beside the search. Anything that
 * is not a plain id is dropped rather than stored: the column is there for counting, and
 * a value carrying punctuation is either a mistake or somebody trying something.
 */
class ClientContextTest {

    @AfterEach
    void tidy() {
        ClientContext.clear();
    }

    @Test
    @DisplayName("a plain id and client are kept")
    void keepsAPlainId() {
        ClientContext.set("a1b2c3d4e5f6a1b2c3d4e5f6", "app");

        assertThat(ClientContext.deviceId()).isEqualTo("a1b2c3d4e5f6a1b2c3d4e5f6");
        assertThat(ClientContext.client()).isEqualTo("app");
    }

    @Test
    @DisplayName("nothing else is")
    void refusesAnythingElse() {
        ClientContext.set("drop table stop;--", "app");
        assertThat(ClientContext.deviceId()).isNull();

        ClientContext.set("x".repeat(65), "app");
        assertThat(ClientContext.deviceId()).isNull();

        ClientContext.set("   ", "app");
        assertThat(ClientContext.deviceId()).isNull();
    }

    @Test
    @DisplayName("an app that shares nothing is anonymous, not an error")
    void allowsNoId() {
        ClientContext.set(null, null);

        assertThat(ClientContext.deviceId()).isNull();
        assertThat(ClientContext.client()).isNull();
    }

    @Test
    @DisplayName("a search the app answered from its own copy is marked as such")
    void marksCachedSearches() {
        ClientContext.set("a1b2c3d4", "app");

        SearchAnalyticsEvent event = SearchAnalyticsEvent.cached("/api/plan", null, null, 3);

        assertThat(event.cached()).isTrue();
        assertThat(event.optionCount()).isEqualTo(3);
        assertThat(event.deviceId()).isEqualTo("a1b2c3d4");
        // A live search is not marked, so one can be counted without the other.
        assertThat(SearchAnalyticsEvent.of("/api/plan", null, null, java.util.List.of(), 5).cached()).isFalse();
    }
}
