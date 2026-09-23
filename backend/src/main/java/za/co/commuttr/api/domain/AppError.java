package za.co.commuttr.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.OffsetDateTime;

/** A row of {@code app_error}: something the app could not handle, as the app saw it. */
@Entity
@Table(name = "app_error")
public class AppError {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "device_id")
    private String deviceId;

    @Column(name = "client")
    private String client;

    @Column(name = "app_version")
    private String appVersion;

    @Column(name = "platform")
    private String platform;

    @Column(name = "kind", nullable = false)
    private String kind;

    @Column(name = "message", nullable = false)
    private String message;

    @Column(name = "where_at")
    private String where;

    @Column(name = "happened_at", nullable = false)
    private OffsetDateTime happenedAt;

    protected AppError() { }

    public AppError(String deviceId, String client, String appVersion, String platform,
                    String kind, String message, String where, OffsetDateTime happenedAt) {
        this.deviceId = deviceId;
        this.client = client;
        this.appVersion = appVersion;
        this.platform = platform;
        this.kind = kind;
        this.message = message;
        this.where = where;
        this.happenedAt = happenedAt;
    }

    public Long getId() { return id; }
    public String getMessage() { return message; }
}
