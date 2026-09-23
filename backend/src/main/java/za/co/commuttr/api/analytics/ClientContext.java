package za.co.commuttr.api.analytics;

import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Component;

import java.io.IOException;

/**
 * Who is asking, for the one request being served.
 *
 * <p>A search row said what was searched and never by whom, so the only question it could
 * answer was "how many searches". Operators and the City ask "how many people", and 500
 * searches can be 500 commuters or one. The app sends a random value it makes on first
 * launch, which says two searches came from the same phone WITHOUT saying whose phone.
 * It is not a device identifier: the rider can clear it, and turning sharing off stops it
 * being sent at all.
 *
 * <p>It lives in a thread local because the search row is written on another thread, and
 * the analytics event is built while the request thread is still the one running. Nothing
 * outside analytics reads it, and the filter always clears it, so it cannot leak into the
 * next request on a reused thread.
 */
@Component
public class ClientContext implements Filter {

    /** Header the app sends: a random id it made, or absent when sharing is off. */
    public static final String DEVICE_HEADER = "X-Commuttr-Device";

    /** Header naming the front end: "app", "web". */
    public static final String CLIENT_HEADER = "X-Commuttr-Client";

    /** Long enough for a UUID, short enough that nothing else can be smuggled in. */
    private static final int MAX_LENGTH = 64;

    private static final ThreadLocal<String[]> CURRENT = new ThreadLocal<>();

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        if (request instanceof HttpServletRequest http) {
            CURRENT.set(new String[] {
                    clean(http.getHeader(DEVICE_HEADER)),
                    clean(http.getHeader(CLIENT_HEADER)),
            });
        }
        try {
            chain.doFilter(request, response);
        } finally {
            CURRENT.remove();
        }
    }

    private static String clean(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        if (trimmed.isEmpty() || trimmed.length() > MAX_LENGTH) {
            return null;
        }
        return trimmed.chars().allMatch(c -> Character.isLetterOrDigit(c) || c == '-' || c == '_')
                ? trimmed
                : null;
    }

    /** The device id of the request being served, or null. */
    public static String deviceId() {
        String[] current = CURRENT.get();
        return current == null ? null : current[0];
    }

    /** Which front end is asking, or null. */
    public static String client() {
        String[] current = CURRENT.get();
        return current == null ? null : current[1];
    }

    /** For tests and for work that is not serving a request. */
    public static void set(String deviceId, String client) {
        CURRENT.set(new String[] { clean(deviceId), clean(client) });
    }

    public static void clear() {
        CURRENT.remove();
    }
}
