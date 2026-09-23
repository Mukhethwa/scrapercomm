package za.co.commuttr.api.web;

import jakarta.persistence.EntityManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Is Commuttr up, and is its data current? Public, and deliberately so.
 *
 * <p>{@code /api/health} answers whether the process is running, which any uptime monitor
 * can poll but which stays "ok" while the timetables quietly go a month out of date. The
 * thing that actually goes wrong here is staleness, and nothing outside the database could
 * see it.
 *
 * <p>So this says how old each operator's data is and whether that is inside the limit the
 * loaders are scheduled for. A monitor can watch one URL; an API customer can check what
 * they are paying for without asking; and a rider's bug report can be answered with a fact.
 *
 * <p>Nothing here is about a person. It is counts and dates, which is why it needs no
 * token - the alternative is a status page nobody can see, which is not a status page.
 */
@RestController
@RequestMapping("/api")
public class StatusController {

    /**
     * How old each operator's data may be before this reports it stale.
     *
     * The same numbers as gabs_scraper.freshness, and they must stay the same: a monitor
     * watching this endpoint and an operator running that command should not disagree
     * about whether the data is current.
     *
     * <p>They sit above the refresh interval rather than on it. The refresh runs
     * fortnightly, so a 14-day limit would be reached in the hours before each run and
     * this would report stale data every fortnight, on schedule, for data about to be
     * replaced. 18 days leaves room for one run to fail and be noticed.
     */
    private static final Map<String, Integer> MAX_AGE_DAYS =
            Map.of("gabs", 18, "myciti", 120, "metrorail", 120);

    private final EntityManager em;

    public StatusController(EntityManager em) {
        this.em = em;
    }

    @GetMapping("/status")
    @Transactional(readOnly = true)
    @SuppressWarnings("unchecked")
    public Map<String, Object> status() {
        List<Object[]> rows = em.createNativeQuery("""
                SELECT o.code,
                       count(DISTINCT t.id)                                             AS timetables,
                       max(t.scraped_at)::date                                          AS last_load,
                       (now()::date - max(t.scraped_at)::date)                          AS age_days,
                       count(DISTINCT t.id) FILTER (WHERE t.effective_to < now()::date) AS expired
                FROM operator o
                LEFT JOIN route r     ON r.operator_id = o.id
                LEFT JOIN timetable t ON t.route_id = r.id
                GROUP BY o.code ORDER BY o.code
                """).getResultList();

        List<Map<String, Object>> operators = new java.util.ArrayList<>();
        boolean allFresh = true;
        for (Object[] r : rows) {
            String code = (String) r[0];
            Integer age = r[3] == null ? null : ((Number) r[3]).intValue();
            int limit = MAX_AGE_DAYS.getOrDefault(code, 120);
            boolean fresh = age != null && age <= limit;
            allFresh &= fresh;

            Map<String, Object> row = new LinkedHashMap<>();
            row.put("operator", code);
            row.put("timetables", ((Number) r[1]).longValue());
            row.put("last_loaded", r[2] == null ? null : r[2].toString());
            row.put("days_old", age);
            row.put("expired_timetables", ((Number) r[4]).longValue());
            row.put("fresh", fresh);
            operators.add(row);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        // "ok" means the API answers AND the data is inside its limits, because an API
        // serving month-old timetables is not a service anybody wants monitored as up.
        out.put("status", allFresh ? "ok" : "stale_data");
        out.put("operators", operators);
        return out;
    }
}
