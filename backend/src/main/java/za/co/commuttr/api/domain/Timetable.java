package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/** Maps sql/schema.sql :: timetable. One row per scraped PDF version. */
@Entity
@Immutable
@Table(name = "timetable")
public class Timetable {

    @Id
    @Column(name = "id")
    private Integer id;

    @Column(name = "route_id", nullable = false)
    private Integer routeId;

    @Column(name = "timetable_number")
    private String timetableNumber;

    @Column(name = "is_public_holiday", nullable = false)
    private boolean publicHoliday;

    @Column(name = "effective_from")
    private LocalDate effectiveFrom;

    @Column(name = "effective_to")
    private LocalDate effectiveTo;

    @Column(name = "pdf_url")
    private String pdfUrl;

    @Column(name = "pdf_filename", nullable = false)
    private String pdfFilename;

    @Column(name = "pdf_sha256")
    private String pdfSha256;

    @Column(name = "page_count")
    private Integer pageCount;

    /** Large fallback blob. The API never selects it; projections are used instead. */
    @Column(name = "raw_text")
    private String rawText;

    @Column(name = "parse_status", nullable = false)
    private String parseStatus;

    @Column(name = "parse_error")
    private String parseError;

    @Column(name = "scraped_at")
    private OffsetDateTime scrapedAt;

    @Column(name = "parsed_at")
    private OffsetDateTime parsedAt;

    public Integer getId() { return id; }
    public Integer getRouteId() { return routeId; }
    public String getTimetableNumber() { return timetableNumber; }
    public boolean isPublicHoliday() { return publicHoliday; }
    public LocalDate getEffectiveFrom() { return effectiveFrom; }
    public LocalDate getEffectiveTo() { return effectiveTo; }
    public String getPdfUrl() { return pdfUrl; }
    public String getPdfFilename() { return pdfFilename; }
    public String getPdfSha256() { return pdfSha256; }
    public Integer getPageCount() { return pageCount; }
    public String getRawText() { return rawText; }
    public String getParseStatus() { return parseStatus; }
    public String getParseError() { return parseError; }
    public OffsetDateTime getScrapedAt() { return scrapedAt; }
    public OffsetDateTime getParsedAt() { return parsedAt; }
}
