package za.co.commuttr.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Commuttr API — the Java port of the read-only FastAPI server over the GABS timetable
 * database.
 *
 * <p>Everything in this service is read-only against the scraper's schema; the single
 * exception is the additive {@code search_analytics} table. The Python scraper keeps
 * ingesting Golden Arrow data exactly as before.
 *
 * <pre>
 *   mvn -f backend/pom.xml spring-boot:run
 * </pre>
 */
@SpringBootApplication
public class CommuttrApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(CommuttrApiApplication.class, args);
    }
}
