package za.co.commuttr.api.web;

import jakarta.persistence.EntityManager;
import jakarta.persistence.Query;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The dashboard behind the app: what we hold, how old it is, and what riders searched.
 *
 * <p>Everything here was already answerable with psql and a query somebody had to
 * remember. That is fine while the database is on the same machine as the person asking,
 * and no use at all once the API is deployed - which is when "is the data stale" starts
 * mattering most, because nobody is watching it.
 *
 * <p>Read-only, with one exception: the refresh button writes a row asking for a reload.
 * It does not run anything. A web endpoint that starts a process on the server is a much
 * bigger door than this needs, and the scheduled script is already the thing that knows
 * how to do a reload properly; it picks the request up and marks it done.
 *
 * <p>Locked behind a token in {@code COMMUTTR_ADMIN_TOKEN}. With none set, every route
 * here answers 503 and says so, so an unconfigured deployment exposes nothing rather than
 * everything.
 */
@RestController
@RequestMapping("/api/admin")
public class AdminController {

    private final EntityManager em;
    private final String token;

    public AdminController(EntityManager em,
                           @Value("${commuttr.admin.token:}") String token) {
        this.em = em;
        this.token = token == null ? "" : token.trim();
    }

    /** 503 when no token is configured, 401 when the wrong one is given, else null. */
    private ResponseEntity<Object> refuse(String given) {
        if (token.isEmpty()) {
            return ResponseEntity.status(503).body(Map.of(
                    "detail", "The dashboard is switched off. Set COMMUTTR_ADMIN_TOKEN on the API and restart."));
        }
        String offered = given == null ? "" : given.replaceFirst("^(?i)bearer ", "").trim();
        // Constant time, so the token cannot be guessed a character at a time.
        if (!java.security.MessageDigest.isEqual(
                offered.getBytes(StandardCharsets.UTF_8), token.getBytes(StandardCharsets.UTF_8))) {
            return ResponseEntity.status(401).body(Map.of("detail", "Wrong or missing dashboard token."));
        }
        return null;
    }

    /** The page itself. It asks for the token and keeps it in the browser. */
    @GetMapping(value = "/page", produces = MediaType.TEXT_HTML_VALUE)
    public ResponseEntity<String> page() throws IOException {
        String html = new String(new ClassPathResource("admin/dashboard.html")
                .getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .body(html);
    }

    @GetMapping("/summary")
    @Transactional(readOnly = true)
    public ResponseEntity<Object> summary(@RequestHeader(value = "Authorization", required = false) String auth) {
        ResponseEntity<Object> no = refuse(auth);
        if (no != null) {
            return no;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("operators", rows("""
                SELECT o.code, o.name, o.kind,
                       count(DISTINCT r.id)                                    AS routes,
                       count(DISTINCT t.id)                                    AS timetables,
                       count(DISTINCT sc.id)                                   AS schedules,
                       max(t.scraped_at)                                       AS last_load,
                       (now()::date - max(t.scraped_at)::date)                 AS age_days,
                       count(DISTINCT t.id) FILTER (WHERE t.effective_to < now()::date) AS expired,
                       count(DISTINCT t.id) FILTER (WHERE t.pdf_url IS NULL)   AS without_pdf
                FROM operator o
                LEFT JOIN route r     ON r.operator_id = o.id
                LEFT JOIN timetable t ON t.route_id = r.id
                LEFT JOIN schedule sc ON sc.timetable_id = t.id
                GROUP BY o.code, o.name, o.kind
                ORDER BY o.code
                """));
        out.put("stops", rows("""
                SELECT o.code,
                       count(*)                                  AS stops,
                       count(*) FILTER (WHERE s.lat IS NULL)     AS unplaced
                FROM stop s JOIN operator o ON o.id = s.operator_id
                GROUP BY o.code ORDER BY o.code
                """));
        out.put("totals", rows("""
                SELECT (SELECT count(*) FROM stop)                AS stops,
                       (SELECT count(*) FROM route)               AS routes,
                       (SELECT count(*) FROM timetable)           AS timetables,
                       (SELECT count(*) FROM schedule)            AS schedules,
                       (SELECT count(*) FROM stop_time)           AS stop_times,
                       (SELECT count(*) FROM journey_fare)        AS fares,
                       (SELECT count(*) FROM leg_geometry)        AS leg_paths
                """).get(0));
        out.put("searches", rows("""
                SELECT count(*)                                              AS searches,
                       count(DISTINCT device_id)                             AS phones,
                       count(*) FILTER (WHERE cached)                        AS answered_offline,
                       count(*) FILTER (WHERE endpoint = '/api/connections') AS with_a_change,
                       count(*) FILTER (WHERE option_count = 0)              AS found_nothing
                FROM search_analytics
                WHERE searched_at > now() - interval '30 days'
                """).get(0));
        out.put("last_run", first("""
                SELECT id, operators, started_at, finished_at, ok, detail
                FROM refresh_run ORDER BY started_at DESC LIMIT 1
                """));
        out.put("pending", rows("""
                SELECT id, operators, requested_at, requested_by
                FROM refresh_request WHERE done_at IS NULL ORDER BY requested_at
                """));
        return ResponseEntity.ok(out);
    }

    /** Every route we serve, newest data first, filtered by operator or by name. */
    @GetMapping("/routes")
    @Transactional(readOnly = true)
    public ResponseEntity<Object> routes(@RequestHeader(value = "Authorization", required = false) String auth,
                                         @RequestParam(value = "operator", required = false) String operator,
                                         @RequestParam(value = "q", required = false) String q,
                                         @RequestParam(value = "limit", defaultValue = "200") int limit) {
        ResponseEntity<Object> no = refuse(auth);
        if (no != null) {
            return no;
        }
        Query query = em.createNativeQuery("""
                SELECT r.id, r.name, o.code AS operator, count(DISTINCT t.id) AS timetables,
                       max(t.effective_from) AS newest_from,
                       max(t.scraped_at)     AS last_load,
                       bool_or(t.effective_to IS NULL OR t.effective_to >= now()::date) AS current,
                       count(DISTINCT t.id) FILTER (WHERE t.pdf_url IS NOT NULL) AS with_pdf
                FROM route r
                JOIN operator o ON o.id = r.operator_id
                LEFT JOIN timetable t ON t.route_id = r.id
                -- Cast, because Postgres cannot infer the type of a bare parameter that
                -- is only ever compared to NULL, and refuses the statement outright.
                WHERE (CAST(:operator AS text) IS NULL OR o.code = CAST(:operator AS text))
                  AND (CAST(:q AS text) IS NULL OR r.name ILIKE '%' || CAST(:q AS text) || '%')
                GROUP BY r.id, r.name, o.code
                ORDER BY r.name
                LIMIT :limit
                """);
        query.setParameter("operator", blankToNull(operator));
        query.setParameter("q", blankToNull(q));
        query.setParameter("limit", Math.min(Math.max(limit, 1), 1000));
        return ResponseEntity.ok(Map.of("routes", asMaps(query)));
    }

    /** What riders looked for: places, routes, and the searches that found nothing. */
    @GetMapping("/demand")
    @Transactional(readOnly = true)
    public ResponseEntity<Object> demand(@RequestHeader(value = "Authorization", required = false) String auth,
                                         @RequestParam(value = "days", defaultValue = "30") int days) {
        ResponseEntity<Object> no = refuse(auth);
        if (no != null) {
            return no;
        }
        int window = Math.min(Math.max(days, 1), 365);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("days", window);
        out.put("destinations", rows("""
                SELECT s.name, count(*) AS searches
                FROM search_analytics a JOIN stop s ON s.id = a.to_stop_id
                WHERE a.searched_at > now() - make_interval(days => %d)
                GROUP BY s.name ORDER BY searches DESC LIMIT 15
                """.formatted(window)));
        out.put("routes", rows("""
                SELECT o.route_label AS name, count(*) AS offered
                FROM search_analytics_option o
                JOIN search_analytics a ON a.id = o.search_id
                WHERE a.searched_at > now() - make_interval(days => %d) AND o.route_label IS NOT NULL
                GROUP BY o.route_label ORDER BY offered DESC LIMIT 15
                """.formatted(window)));
        out.put("not_found", rows("""
                SELECT lower(query) AS looked_for, count(*) AS times
                FROM place_search
                WHERE result_count = 0 AND searched_at > now() - make_interval(days => %d)
                GROUP BY 1 ORDER BY times DESC LIMIT 15
                """.formatted(window)));
        return ResponseEntity.ok(out);
    }

    /** Recent reloads, so "when did this last work" is on the screen. */
    @GetMapping("/refreshes")
    @Transactional(readOnly = true)
    public ResponseEntity<Object> refreshes(@RequestHeader(value = "Authorization", required = false) String auth) {
        ResponseEntity<Object> no = refuse(auth);
        if (no != null) {
            return no;
        }
        return ResponseEntity.ok(Map.of("runs", rows("""
                SELECT id, operators, started_at, finished_at, ok, detail, log_path
                FROM refresh_run ORDER BY started_at DESC LIMIT 20
                """)));
    }

    public record RefreshRequest(String operators, String by) { }

    /**
     * Ask for a reload. Writes a row; the scheduled script does the work.
     *
     * <p>Deliberately not "run it now". The reload downloads and parses every timetable
     * PDF, takes many minutes, and needs Python, Docker and the operators' sites - none of
     * which belong behind an HTTP request that a browser is waiting on.
     */
    @PostMapping("/refresh")
    @Transactional
    public ResponseEntity<Object> requestRefresh(
            @RequestHeader(value = "Authorization", required = false) String auth,
            @RequestBody(required = false) RefreshRequest body) {
        ResponseEntity<Object> no = refuse(auth);
        if (no != null) {
            return no;
        }
        String operators = body == null || body.operators() == null || body.operators().isBlank()
                ? "all" : body.operators().trim();
        if (!List.of("all", "gabs", "myciti", "metrorail").contains(operators)) {
            return ResponseEntity.badRequest().body(Map.of("detail", "Unknown operator: " + operators));
        }
        em.createNativeQuery("""
                INSERT INTO refresh_request (operators, requested_by) VALUES (:operators, :by)
                """)
                .setParameter("operators", operators)
                .setParameter("by", body == null || body.by() == null ? "dashboard" : body.by())
                .executeUpdate();
        return ResponseEntity.accepted().body(Map.of(
                "requested", operators,
                "detail", "The next scheduled refresh will pick this up. To run it now: scripts/refresh.ps1"));
    }

    // ------------------------------------------------------------------ plumbing

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s.trim();
    }

    private List<Map<String, Object>> rows(String sql) {
        return asMaps(em.createNativeQuery(sql));
    }

    private Map<String, Object> first(String sql) {
        List<Map<String, Object>> all = rows(sql);
        return all.isEmpty() ? null : all.get(0);
    }

    /**
     * Native rows as maps, keyed by column name.
     *
     * <p>Hibernate hands back tuples; the dashboard wants JSON with names on it. Numbers
     * come back as BigDecimal or BigInteger, which JSON renders with a trailing ".0" that
     * reads oddly next to a count, so whole numbers are sent as longs.
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> asMaps(Query query) {
        query.unwrap(org.hibernate.query.NativeQuery.class)
                .setTupleTransformer((tuple, aliases) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    for (int i = 0; i < aliases.length; i++) {
                        row.put(aliases[i].toLowerCase(), plain(tuple[i]));
                    }
                    return row;
                });
        return new ArrayList<>(query.getResultList());
    }

    private static Object plain(Object value) {
        if (value instanceof BigDecimal d) {
            return d.stripTrailingZeros().scale() <= 0 ? d.longValue() : d.doubleValue();
        }
        if (value instanceof java.math.BigInteger b) {
            return b.longValue();
        }
        if (value instanceof java.sql.Timestamp t) {
            return t.toInstant().toString();
        }
        if (value instanceof java.sql.Date d) {
            return d.toLocalDate().toString();
        }
        return value;
    }
}
