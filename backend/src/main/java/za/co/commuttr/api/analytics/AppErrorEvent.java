package za.co.commuttr.api.analytics;

import java.time.OffsetDateTime;

/**
 * An error the app could not handle, reported by the app itself.
 *
 * <p>Commuttr promises riders no third-party trackers and no analytics SDKs, which is the
 * right promise and also rules out every usual way of finding out that a build crashes.
 * This is the replacement: the app tells us, over the same switch and the same anonymous
 * id as everything else.
 *
 * @param where the top frames of the stack, trimmed - enough to find the code, and
 *              nothing about what was on the screen
 */
public record AppErrorEvent(String appVersion,
                            String platform,
                            String kind,
                            String message,
                            String where,
                            String deviceId,
                            String client,
                            OffsetDateTime happenedAt) {

    public static AppErrorEvent of(String appVersion, String platform, String message, String where) {
        return new AppErrorEvent(appVersion, platform, "flutter", message, where,
                ClientContext.deviceId(), ClientContext.client(), OffsetDateTime.now());
    }
}
