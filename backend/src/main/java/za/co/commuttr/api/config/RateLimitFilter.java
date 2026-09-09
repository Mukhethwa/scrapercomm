package za.co.commuttr.api.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * A ceiling on how fast one caller can ask.
 *
 * <p>The API is read-only and public, so there is nothing here to protect from
 * vandalism - what needs protecting is the database and the thread pool. A journey search
 * from a place is seconds of work, and nothing stopped a script from starting a thousand
 * of them. One impatient tester with a reload key, or one crawler, could take the app down
 * for everybody else without meaning any harm.
 *
 * <p>A fixed window per caller per minute, held in memory. Not distributed and not
 * durable, because this runs as one process; if that stops being true this belongs in
 * front of the app rather than inside it.
 *
 * <p>Deliberately generous. A rider typing into the search box makes a handful of requests
 * a second while the debounce fires, and a limit that catches a real person is worse than
 * no limit at all - they cannot tell it from the app being broken. The number here is
 * about twenty times what using the app looks like.
 */
@Component
public class RateLimitFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(RateLimitFilter.class);

    /** Callers seen this window, and how many requests each has made. */
    private final Map<String, AtomicInteger> counts = new ConcurrentHashMap<>();
    private volatile long windowStartedAt = System.currentTimeMillis();

    private final int perMinute;

    /**
     * Bounded, so a flood of distinct addresses cannot exhaust memory in the course of
     * defending against a flood of requests.
     */
    private static final int MAX_TRACKED = 20_000;
    private static final long WINDOW_MS = 60_000;

    public RateLimitFilter(@Value("${commuttr.rate-limit.per-minute:300}") int perMinute) {
        this.perMinute = perMinute;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        // Only the API. The built UI is static files and is not worth counting.
        return !request.getRequestURI().startsWith("/api/");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        if (perMinute <= 0) {           // switched off by configuration
            chain.doFilter(request, response);
            return;
        }

        long now = System.currentTimeMillis();
        if (now - windowStartedAt >= WINDOW_MS) {
            synchronized (this) {
                if (now - windowStartedAt >= WINDOW_MS) {
                    counts.clear();
                    windowStartedAt = now;
                }
            }
        }

        String caller = callerOf(request);
        int used = counts.size() >= MAX_TRACKED && !counts.containsKey(caller)
                ? 1                     // over the tracking cap: let it through rather
                                        // than start refusing everybody
                : counts.computeIfAbsent(caller, k -> new AtomicInteger()).incrementAndGet();

        if (used > perMinute) {
            if (used == perMinute + 1) {
                log.warn("rate limit reached for {} ({} requests in a minute)", caller, used);
            }
            response.setStatus(429);
            response.setHeader("Retry-After",
                    String.valueOf(Math.max(1, (WINDOW_MS - (now - windowStartedAt)) / 1000)));
            response.setContentType("application/json");
            response.getWriter().write(
                    "{\"error\":\"Too many requests. Please slow down and try again shortly.\"}");
            return;
        }
        chain.doFilter(request, response);
    }

    /**
     * Who is asking.
     *
     * <p>X-Forwarded-For where a proxy set it - the app is served through ngrok today and
     * would sit behind something similar in production, and without this every request
     * would count against the proxy as a single caller. The leftmost entry is the one the
     * client claimed, which is forgeable; that is acceptable for a courtesy limit on a
     * read-only API and would not be for anything that mattered.
     */
    private static String callerOf(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        String remote = request.getRemoteAddr();
        return remote == null ? "unknown" : remote;
    }
}
