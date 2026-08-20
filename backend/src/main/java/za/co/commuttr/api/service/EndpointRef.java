package za.co.commuttr.api.service;

/**
 * A journey endpoint: either a named stop or a dropped pin. The Java equivalent of the
 * {@code {"kind": "stop"|"pin", ...}} dict that {@code api._endpoint} produced.
 */
public record EndpointRef(String kind, Integer stopId, Double lat, Double lon) {

    public static final String STOP = "stop";
    public static final String PIN = "pin";

    public static EndpointRef stop(Integer stopId) {
        return new EndpointRef(STOP, stopId, null, null);
    }

    public static EndpointRef pin(double lat, double lon) {
        return new EndpointRef(PIN, null, lat, lon);
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

    public boolean isStop() {
        return STOP.equals(kind);
    }
}
