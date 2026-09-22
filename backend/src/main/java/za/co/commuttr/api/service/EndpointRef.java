package za.co.commuttr.api.service;

/**
 * A journey endpoint: either a named stop or a dropped pin. The Java equivalent of the
 * {@code {"kind": "stop"|"pin", ...}} dict that {@code api._endpoint} produced.
 */
/**
 * @param name what the rider called a point, when they chose a named place ("Khayelitsha").
 *             A stop or station of exactly that name is where they mean, however far the
 *             place's own coordinates are from it. Null for a stop, a dropped pin, or your
 *             location.
 */
public record EndpointRef(String kind, Integer stopId, Double lat, Double lon, String name) {

    public static final String STOP = "stop";
    public static final String PIN = "pin";

    public static EndpointRef stop(Integer stopId) {
        return new EndpointRef(STOP, stopId, null, null, null);
    }

    public static EndpointRef pin(double lat, double lon) {
        return new EndpointRef(PIN, null, lat, lon, null);
    }

    /**
     * {@code api._endpoint}: a stop id wins; otherwise both coordinates must be present.
     * Returns null when neither is supplied, which the caller turns into a 400.
     */
    public static EndpointRef of(Integer stopId, Double lat, Double lon) {
        if (stopId != null) {
            return stop(stopId);
        }
        if (lat != null && lon != null) {
            return pin(lat, lon);
        }
        return null;
    }

    /** The same point, named as the rider named it. Blank names are no name. */
    public EndpointRef withName(String placeName) {
        String n = placeName == null || placeName.isBlank() ? null : placeName.trim();
        return isStop() ? this : new EndpointRef(kind, stopId, lat, lon, n);
    }

    public boolean isStop() {
        return STOP.equals(kind);
    }
}
