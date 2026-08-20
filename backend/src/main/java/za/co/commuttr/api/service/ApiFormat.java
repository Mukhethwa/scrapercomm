package za.co.commuttr.api.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;

/**
 * The exact value formatting the FastAPI service used, kept in one place so every
 * endpoint renders times and dates identically.
 */
public final class ApiFormat {

    private static final DateTimeFormatter HH_MM = DateTimeFormatter.ofPattern("HH:mm");

    private ApiFormat() { }

    /** {@code _fmt_time}: "HH:MM", or null. */
    public static String time(LocalTime value) {
        return value == null ? null : value.format(HH_MM);
    }

    /** {@code date.isoformat()}: "YYYY-MM-DD", or null. */
    public static String date(LocalDate value) {
        return value == null ? null : value.toString();
    }

    /** {@code _min}: a wall-clock time as minutes past midnight, or null. */
    public static Integer minutes(LocalTime value) {
        return value == null ? null : value.getHour() * 60 + value.getMinute();
    }

    /**
     * {@code _mmss}: minutes past midnight rendered as "HH:MM", wrapping past 24h.
     * Uses {@link Math#rint} (half-to-even) to match Python's {@code round}, and
     * floor-based div/mod to match Python's {@code //} and {@code %}.
     */
    public static String minutesToClock(Number minutes) {
        if (minutes == null) {
            return null;
        }
        int m = (int) Math.rint(minutes.doubleValue());
        return String.format("%02d:%02d", Math.floorMod(Math.floorDiv(m, 60), 24), Math.floorMod(m, 60));
    }

    /**
     * Python's {@code round(value, scale)}: half-to-even over the shortest decimal
     * representation of the double, so results match the FastAPI payloads digit for digit.
     */
    public static double roundTo(double value, int scale) {
        return BigDecimal.valueOf(value).setScale(scale, RoundingMode.HALF_EVEN).doubleValue();
    }

    /** Python's {@code round(value)} with no scale: half-to-even to a whole number. */
    public static long roundToLong(double value) {
        return BigDecimal.valueOf(value).setScale(0, RoundingMode.HALF_EVEN).longValue();
    }
}
