package za.co.commuttr.api.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;

import java.io.IOException;
import java.net.URI;

/**
 * The Strangler Fig facade.
 *
 * <p>While the port is in progress this service fronts the legacy FastAPI process: any
 * {@code /api/**} request that no Spring controller claims is forwarded to the Python
 * app and its response returned untouched. Endpoints migrate one at a time, and the
 * React client keeps talking to a single origin throughout.
 *
 * <p>Disabled by default — every endpoint in the FastAPI service has been ported, so the
 * vine has already strangled the tree. Enable it (with the legacy app moved to another
 * port) if you want to cut over incrementally or roll a single endpoint back:
 *
 * <pre>
 *   LEGACY_FALLBACK_ENABLED=true LEGACY_BASE_URL=http://localhost:8001
 * </pre>
 */
@Component
@Order(Ordered.LOWEST_PRECEDENCE)
@ConditionalOnProperty(name = "commuttr.legacy.enabled", havingValue = "true")
public class LegacyFallbackFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(LegacyFallbackFilter.class);

    private final ObjectProvider<RequestMappingHandlerMapping> handlerMapping;
    private final RestClient legacy;
    private final String baseUrl;

    public LegacyFallbackFilter(ObjectProvider<RequestMappingHandlerMapping> handlerMapping,
                                RestClient.Builder builder,
                                @Value("${commuttr.legacy.base-url}") String baseUrl) {
        this.handlerMapping = handlerMapping;
        this.baseUrl = baseUrl.replaceAll("/+$", "");
        this.legacy = builder.build();
        log.info("Strangler Fig fallback is ON — unmigrated /api paths go to {}", this.baseUrl);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith("/api/");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        if (isHandledLocally(request)) {
            chain.doFilter(request, response);
            return;
        }

        String query = request.getQueryString();
        URI target = URI.create(baseUrl + request.getRequestURI() + (query == null ? "" : "?" + query));
        log.debug("Forwarding {} to the legacy service", target);

        try {
            ResponseEntity<byte[]> upstream = legacy.method(
                            org.springframework.http.HttpMethod.valueOf(request.getMethod()))
                    .uri(target)
                    .retrieve()
                    .onStatus(status -> true, (req, res) -> { }) // pass every status through
                    .toEntity(byte[].class);

            response.setStatus(upstream.getStatusCode().value());
            if (upstream.getHeaders().getContentType() != null) {
                response.setContentType(upstream.getHeaders().getContentType().toString());
            }
            byte[] body = upstream.getBody();
            if (body != null) {
                response.getOutputStream().write(body);
            }
        } catch (Exception ex) {
            log.error("Legacy service at {} did not answer", target, ex);
            response.setStatus(HttpServletResponse.SC_BAD_GATEWAY);
            response.setContentType("application/json");
            response.getWriter().write("{\"detail\":\"legacy service unavailable\"}");
        }
    }

    /** True when a Spring controller claims this path, i.e. the endpoint is migrated. */
    private boolean isHandledLocally(HttpServletRequest request) {
        RequestMappingHandlerMapping mapping = handlerMapping.getIfAvailable();
        if (mapping == null) {
            return true;
        }
        try {
            return mapping.getHandler(request) != null;
        } catch (Exception ex) {
            // A method/media-type mismatch still means we own the path.
            return true;
        }
    }
}
