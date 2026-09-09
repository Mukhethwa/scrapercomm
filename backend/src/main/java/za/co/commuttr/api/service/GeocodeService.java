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
import za.co.commuttr.api.repo.AreaRepository;
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
import java.util.Set;

/**
 * GET /api/geocode - the areas a rider can name.
 *
 * <p><b>Answered locally.</b> The 728 named places of the metro were fetched once from
 * OpenStreetMap and live in the {@code area} table; see {@code gabs_scraper.areas}. This
 * asked Nominatim on every pause in typing, which is a request per keystroke per user
 * against a service whose usage policy is one request a second for the whole application.
 * That is fine for one developer and impossible in public - and a rate-limited Nominatim
 * does not announce itself, it simply returns nothing, which the app can only report as
 * "no such place". WOODSTOCK and SALT RIVER disappeared from Commuttr exactly that way.
 *
 * <p>It also could not do what a search box most needs. Nominatim matches whole words, so
 * "woodst" found nothing while the stop list beside it in the same menu completed the name
 * happily. Locally it is a prefix match, so the two halves of the menu behave alike.
 *
 * <p>Nominatim is still the fallback for a query the table cannot answer, which is rare
 * and no longer on the critical path.
 *
 * <p><b>Areas only.</b> Nominatim will happily return a school, a night shelter, a scout
 * hall and a supermarket for "kraaifontein", and offering those as places to travel from
 * is a promise the timetables cannot keep. A pin gets turned into a journey by matching it
 * against the road a bus drives and the stops within walking distance, so naming a
 * building produces "a bus passes here" for a point where, as far as anything published
 * says, no bus stops at all. Golden Arrow's timetables list timing points rather than
 * every kerb, so the app cannot tell the difference between a stop it does not know about
 * and no stop.
 *
 * <p>An area is a claim the data can stand behind: name Kraaifontein and the answer is
 * about Kraaifontein, with the boarding stop named in the result so a rider knows where to
 * walk. That is one entry per area - not the eight things standing inside it.
 *
 * <p><b>And only areas the network reaches.</b> An area is worth offering when a service
 * runs through it, whether or not it is anywhere near the end of a route: Woodstock is
 * somewhere buses drive on the way into town, so a rider coming from Makhaza can get off
 * there, and it belongs in the list even though no route is named after it. Somewhere the
 * network never goes does not, and the only way to find that out used to be to choose it
 * and get an empty screen. {@link PlannerService#isServed} answers it with the same two
 * tests the planner itself would use, so an offered area is one the planner can plan from
 * by construction.
 *
 * <p>The named stops and stations in the same menu come from /api/stops, which is the
 * app's own data, so filtering here removes nothing a rider can actually board at.
 * EERSTE RIVER is not tagged as a place in OSM at all - it comes back as the river - and
 * is still searchable, because it is a station and a bus stop in the database.
 */
@Service
public class GeocodeService {

    private static final Logger log = LoggerFactory.getLogger(GeocodeService.class);

    /** Cape Town and surrounds. */
    private static final String VIEWBOX = "18.28,-33.40,19.12,-34.45";

    /**
     * Settlement-scale places, and nothing else.
     *
     * <p>OSM's {@code class} says what kind of thing a feature is, and "place" is the one
     * that means somewhere people live rather than a building they visit. The types are
     * listed rather than taken wholesale because "place" also covers a province and an
     * ocean, and "Western Cape" is not a journey.
     */
    private static final Set<String> AREA_TYPES = Set.of(
            "city", "town", "borough", "suburb", "quarter", "neighbourhood",
            "village", "hamlet", "locality", "residential", "city_block");

    private static final int PER_LOOKUP = 10;

    /**
     * How many areas the search box is offered.
     *
     * <p>Small on purpose. Filtered to areas, a real query returns one or two - Parow is
     * mapped twice, as a town and as a suburb, and collapses to one row by name - so this
     * is a guard rather than a limit anybody meets.
     */
    private static final int KEEP = 4;

    /**
     * Answers already fetched, keyed by the query.
     *
     * <p>Nominatim's usage policy asks for no more than one request a second, and a search
     * box debounced at 220ms sends one per pause in typing. Riders backspace and retype
     * constantly, so most of those pauses land on a query already answered. Bounded and
     * oldest-out: this is politeness and speed, not a store of anything.
     *
     * <p><b>Answers only.</b> A failed lookup is not an answer and must never be stored as
     * one. It was, and the effect was worse than the outage that caused it: an audit run
     * fired 122 lookups back to back, Nominatim rate-limited most of them exactly as its
     * policy says it will, the failures were swallowed into empty lists, and those empties
     * were cached. WOODSTOCK and SALT RIVER then reported "no such place" for the life of
     * the process - permanent damage from a transient fault, and indistinguishable from a
     * filter that had wrongly excluded them.
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
    private final PlannerService planner;
    private final AreaRepository areas;

    public GeocodeService(RestClient.Builder builder,
                          PlannerService planner,
                          AreaRepository areas,
                          @Value("${commuttr.geocode.base-url}") String baseUrl,
                          @Value("${commuttr.geocode.user-agent}") String userAgent,
                          @Value("${commuttr.geocode.timeout-seconds:20}") long timeoutSeconds) {
        this.baseUrl = baseUrl;
        this.planner = planner;
        this.areas = areas;

        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(timeoutSeconds));
        requestFactory.setReadTimeout(Duration.ofSeconds(timeoutSeconds));

        this.restClient = builder
                .requestFactory(requestFactory)
                .defaultHeader(HttpHeaders.USER_AGENT, userAgent)
                .build();
    }

    /**
     * One lookup, on the bare query.
     *
     * <p>There were two for a while, the second appending ", Cape Town, South Africa".
     * Commas are how Nominatim is told an address hierarchy, so that form asks for what
     * stands INSIDE a named suburb - which is how the schools and shelters were reaching
     * the menu in the first place. Measured over twelve areas it never returned one the
     * bare query missed, and usually returned none at all: filtering to areas leaves the
     * suffixed lookup with nothing to contribute, so it is a request a second that buys
     * nothing.
     */
    public GeocodeResponse geocode(String q) {
        String query = q == null ? "" : q.trim();
        if (query.isEmpty()) {
            return new GeocodeResponse(List.of());
        }
        String cacheKey = query.toLowerCase(Locale.ROOT);

        // The table first, and almost always only the table.
        List<GeoHitDto> local = areas.search("%" + cacheKey + "%", cacheKey + "%",
                                             cacheKey, KEEP).stream()
                .map(a -> new GeoHitDto(a.getName(), a.getFullName(), a.getLat(), a.getLon()))
                .toList();
        if (!local.isEmpty()) {
            return new GeocodeResponse(local);
        }

        List<GeoHitDto> cached = cache.get(cacheKey);
        if (cached != null) {
            return new GeocodeResponse(cached);
        }

        List<Hit> found = lookup(query);
        if (found == null) {
            // The lookup failed rather than found nothing. Answer emptily for now and
            // leave the cache alone, so the next keystroke asks again.
            return new GeocodeResponse(List.of());
        }

        List<GeoHitDto> results = rank(found, query);
        cache.put(cacheKey, results);
        return new GeocodeResponse(results);
    }

    /**
     * The areas Nominatim knows for this query, or null where the lookup itself failed.
     *
     * <p>Null and empty are different answers and the caller treats them differently: an
     * empty list means Nominatim has no area by that name and is worth remembering, null
     * means we do not know and must not pretend to.
     */
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
                    if (!"place".equals(hit.path("class").asText(""))
                            || !AREA_TYPES.contains(hit.path("type").asText(""))) {
                        continue;
                    }
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
            // Warn, not debug. This was silent, so a rate-limited search box looked
            // exactly like a place that does not exist.
            log.warn("Nominatim lookup for '{}' failed: {}", q, ex.toString());
            return null;
        }
        return hits;
    }

    /**
     * The areas in the order a rider reads them.
     *
     * <p>Nominatim's own order is not it. Its ranking is about how well a feature matched
     * the address hierarchy, not about what a word most likely meant. An area whose name
     * IS what was typed comes first here, then one whose name begins with it, then one
     * that merely contains the words, and importance settles the rest.
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

            // One row per area, keyed on the name. Parow is mapped twice, once as a town
            // and once as the suburb inside it, and two identical rows is a choice with no
            // difference behind it.
            Scored existing = best.get(nl);
            if (existing == null || score > existing.score()) {
                best.put(nl, new Scored(h, score));
            }
        }

        // Served areas only, and checked after ranking so the database is asked about a
        // handful of candidates rather than everything Nominatim returned.
        return best.values().stream()
                .sorted((a, b) -> Double.compare(b.score(), a.score()))
                .limit(KEEP)
                .filter(s -> planner.isServed(s.hit().lat(), s.hit().lon()))
                .map(s -> new GeoHitDto(s.hit().name(), s.hit().full(), s.hit().lat(), s.hit().lon()))
                .toList();
    }

    private record Hit(String name, String full, Double lat, Double lon,
                       String osmId, double importance) { }

    private record Scored(Hit hit, double score) { }
}
