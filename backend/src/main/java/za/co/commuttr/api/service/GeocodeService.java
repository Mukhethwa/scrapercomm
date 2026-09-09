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
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * GET /api/geocode - place lookup via OpenStreetMap Nominatim (no API key), used to turn
 * free text into a pin.
 *
 * <p>Two lookups, not one, because Nominatim answers two different questions depending on
 * how the query is punctuated and the search box needs both answers.
 *
 * <p>This used to append ", Cape Town, South Africa" to whatever was typed and send that
 * alone. Commas are how Nominatim is told an address hierarchy, so the suffix turns the
 * whole of what a rider typed into one name to be found <em>inside</em> Cape Town. For a
 * suburb that works well - "kraaifontein, Cape Town, South Africa" returns four things
 * standing in Kraaifontein. For a named place it is fatal: "kraaifontein shoprite, Cape
 * Town, South Africa" returns nothing, because no feature is called "kraaifontein
 * shoprite", while the bare "kraaifontein shoprite" finds the supermarket on 1st Avenue
 * immediately. Measured over ten real searches the suffix cost every result in four of
 * them and gained one in one, and the suffixed form was the only one being asked.
 *
 * <p>Neither form is the better one, so both are asked, in parallel, and the answers
 * merged. The bare query finds a place by its name; the suffixed query finds what stands
 * within a named suburb.
 *
 * <p>Any failure degrades to whatever the other lookup returned, and two failures to an
 * empty list rather than an error, so the search box stays usable when Nominatim is slow
 * or unreachable.
 */
@Service
public class GeocodeService {

    private static final Logger log = LoggerFactory.getLogger(GeocodeService.class);

    /** Cape Town and surrounds. */
    private static final String VIEWBOX = "18.28,-33.40,19.12,-34.45";

    /** Asked of each lookup. The merged list is trimmed to {@link #KEEP}. */
    private static final int PER_LOOKUP = 10;

    /**
     * How many merged places the search box is offered.
     *
     * <p>The old value was five here and three in the browser, and three was too few to
     * hold the answer: "kraaifontein" returns the sea scout group, the high school, the
     * night shelter and then the town of Kraaifontein itself, in that order, so the suburb
     * - the one thing nearly everybody typing that word means - was what fell off the end.
     * Ranking now puts it first, and the extra room means a near miss stays reachable.
     */
    private static final int KEEP = 8;

    /**
     * Answers already fetched, keyed by the query.
     *
     * <p>Nominatim's usage policy asks for no more than one request a second, and a search
     * box debounced at 220ms sends one per pause in typing - now two. Riders backspace and
     * retype constantly, so most of those pauses land on a query already answered. Bounded
     * and oldest-out: this is politeness and speed, not a store of anything.
     */
    private static final int CACHE_MAX = 500;

    private final Map<String, List<GeoHitDto>> cache =
            Collections.synchronizedMap(new LinkedHashMap<String, List<GeoHitDto>>(64, 0.75f, true) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, List<GeoHitDto>> eldest) {
                    return size() > CACHE_MAX;
                }
            });

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
        String query = q == null ? "" : q.trim();
        if (query.isEmpty()) {
            return new GeocodeResponse(List.of());
        }
        String cacheKey = query.toLowerCase(Locale.ROOT);
        List<GeoHitDto> cached = cache.get(cacheKey);
        if (cached != null) {
            return new GeocodeResponse(cached);
        }

        // In parallel: the two lookups are independent and a rider waits for both, so
        // asking twice costs the slower answer rather than the sum of the two.
        CompletableFuture<List<Hit>> bare =
                CompletableFuture.supplyAsync(() -> lookup(query));
        CompletableFuture<List<Hit>> within =
                CompletableFuture.supplyAsync(() -> lookup(query + ", Cape Town, South Africa"));

        List<Hit> merged = new ArrayList<>(bare.join());
        merged.addAll(within.join());

        List<GeoHitDto> results = rank(merged, query);
        cache.put(cacheKey, results);
        return new GeocodeResponse(results);
    }

    /** One Nominatim search, or an empty list where it fails. */
    private List<Hit> lookup(String q) {
        List<Hit> hits = new ArrayList<>();
        try {
            URI uri = UriComponentsBuilder.fromUriString(baseUrl)
                    .queryParam("q", q)
                    .queryParam("format", "json")
                    .queryParam("limit", PER_LOOKUP)
                    .queryParam("countrycodes", "za")
                    .queryParam("viewbox", VIEWBOX)
                    .queryParam("bounded", 0)
                    .build()
                    .encode()
                    .toUri();

            JsonNode results = restClient.get().uri(uri).retrieve().body(JsonNode.class);
            if (results != null && results.isArray()) {
                for (JsonNode hit : results) {
                    String full = hit.path("display_name").asText(q);
                    // Nominatim names the feature outright. The leading component of
                    // display_name is usually that same string, but for anything with a
                    // street number it is the number.
                    String name = hit.path("name").asText("");
                    if (name.isBlank()) {
                        name = full.split(",")[0].trim();
                    }
                    hits.add(new Hit(
                            name,
                            hit.hasNonNull("display_name") ? full : null,
                            Double.parseDouble(hit.get("lat").asText()),
                            Double.parseDouble(hit.get("lon").asText()),
                            hit.path("osm_type").asText("") + "/" + hit.path("osm_id").asText(""),
                            hit.path("importance").asDouble(0.0)));
                }
            }
        } catch (Exception ex) {
            log.debug("Nominatim lookup for '{}' failed, returning no results: {}", q, ex.toString());
            hits.clear();
        }
        return hits;
    }

    /**
     * Merge the two lookups into the order a rider reads them in.
     *
     * <p>Nominatim's own order is not it. For "kraaifontein" it returns the town last of
     * four, behind a sea scout group, because its ranking is about how well a feature
     * matched the address hierarchy rather than about what the word most likely meant. A
     * place whose name IS what was typed comes first here, then one whose name begins with
     * it, then one that merely contains the words, and importance settles the rest.
     */
    private List<GeoHitDto> rank(List<Hit> hits, String query) {
        String ql = query.toLowerCase(Locale.ROOT);
        List<String> words = Arrays.stream(ql.split("\\s+")).filter(w -> !w.isBlank()).toList();

        Map<String, Scored> best = new LinkedHashMap<>();
        for (Hit h : hits) {
            String nl = h.name().toLowerCase(Locale.ROOT);
            double score;
            if (nl.equals(ql)) {
                score = 1000;
            } else if (nl.startsWith(ql)) {
                score = 500;
            } else {
                long matched = words.stream().filter(nl::contains).count();
                score = words.isEmpty() ? 0 : 100.0 * matched / words.size();
            }
            score += h.importance() * 10;

            // The same place found by both lookups is one place. Keyed on the OSM feature
            // where there is one and on the rounded position otherwise, because the two
            // queries can return one feature under two spellings of its street.
            String key = h.osmId().length() > 1
                    ? h.osmId()
                    : String.format(Locale.ROOT, "%.5f,%.5f", h.lat(), h.lon());
            Scored existing = best.get(key);
            if (existing == null || score > existing.score()) {
                best.put(key, new Scored(h, score));
            }
        }

        return best.values().stream()
                .sorted((a, b) -> Double.compare(b.score(), a.score()))
                .limit(KEEP)
                .map(s -> new GeoHitDto(s.hit().name(), s.hit().full(), s.hit().lat(), s.hit().lon()))
                .toList();
    }

    private record Hit(String name, String full, Double lat, Double lon,
                       String osmId, double importance) { }

    private record Scored(Hit hit, double score) { }
}
