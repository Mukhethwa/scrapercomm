package za.co.commuttr.api.service;

/** The commuter-facing ordering of day types, matching {@code _DAY} in the Python API. */
public final class DayTypes {

    private DayTypes() { }

    /** Unknown or missing day types sort last, as {@code _DAY.get(day_type, 9)} did. */
    public static int order(String dayType) {
        if (dayType == null) {
            return 9;
        }
        return switch (dayType) {
            case "WEEKDAY" -> 0;
            case "SATURDAY" -> 1;
            case "SUNDAY" -> 2;
            case "PUBLIC_HOLIDAY" -> 3;
            default -> 9;
        };
    }
}
