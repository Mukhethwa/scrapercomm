package za.co.commuttr.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;
import za.co.commuttr.api.dto.PlanDtos.GeocodeResponse;
import za.co.commuttr.api.dto.PlanDtos.GeoHitDto;

import java.net.URI;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * GET /api/geocode — place/address lookup via OpenStreetMap Nominatim (no API key),
 * used to turn free text into a pin. Ported from {@code api.geocode_place}.
 *
 * <p>Exactly as before, any failure degrades to an empty result list rather than an
 * error, so the search box stays usable when Nominatim is slow or unreachable.
 */
@Service
public class GeocodeService {

    private static final Logger log = LoggerFactory.getLogger(GeocodeService.class);

    /** Cape Town and surrounds. */
    private static final String VIEWBOX = "18.28,-33.40,19.12,-34.45";

    private final RestClient restClient;
    private final String baseUrl;

    public GeocodeService(RestClient.Builder builder,
                          @Value("${commuttr.geocode.base-url}") String baseUrl,
                          @Value("${commuttr.geocode.user-agent}") String userAgent,
                          @Value("${commuttr.geocode.timeout-seconds:20}") long timeoutSeconds) {
        this.baseUrl = baseUrl;

        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(timeoutSeconds));
        requestFactory.setReadTimeout(Duration.ofSeconds(timeoutSeconds));

        this.restClient = builder
                .requestFactory(requestFactory)
                .defaultHeader(HttpHeaders.USER_AGENT, userAgent)
                .build();
    }

    public GeocodeResponse geocode(String q) {
        List<GeoHitDto> hits = new ArrayList<>();
        try {
            URI uri = UriComponentsBuilder.fromUriString(baseUrl)
                    .queryParam("q", q + ", Cape Town, South Africa")
                    .queryParam("format", "json")
                    .queryParam("limit", 5)
                    .queryParam("countrycodes", "za")
                    .queryParam("viewbox", VIEWBOX)
                    .queryParam("bounded", 0)
                    .build()
                    .encode()
                    .toUri();

            JsonNode results = restClient.get().uri(uri).retrieve().body(JsonNode.class);
            if (results != null && results.isArray()) {
                for (JsonNode hit : results) {
                    String displayName = hit.path("display_name").asText(q);
                    hits.add(new GeoHitDto(
                            displayName.split(",")[0],
                            hit.hasNonNull("display_name") ? hit.get("display_name").asText() : null,
                            Double.parseDouble(hit.get("lat").asText()),
                            Double.parseDouble(hit.get("lon").asText())));
                }
            }
        } catch (Exception ex) {
            log.debug("Nominatim lookup for '{}' failed, returning no results: {}", q, ex.toString());
            hits.clear();
        }
        return new GeocodeResponse(hits);
    }
}
