package za.co.commuttr.api.service;

import java.util.ArrayList;
import java.util.List;

/**
 * Pure geo helpers, a direct port of {@code gabs_scraper/geo.py}.
 *
 * <p>Point-to-segment maths uses a local equirectangular projection (accurate at city
 * scale); along-path distances use haversine. No external dependencies.
 */
public final class GeoUtils {

    private static final double R = 6371000.0; // earth radius (m)

    private GeoUtils() { }

    public static double haversineM(double lat1, double lon1, double lat2, double lon2) {
        double p1 = Math.toRadians(lat1);
        double p2 = Math.toRadians(lat2);
        double dp = Math.toRadians(lat2 - lat1);
        double dl = Math.toRadians(lon2 - lon1);
        double a = Math.pow(Math.sin(dp / 2), 2)
                + Math.cos(p1) * Math.cos(p2) * Math.pow(Math.sin(dl / 2), 2);
        return 2 * R * Math.asin(Math.sqrt(a));
    }

    private static double[] xy(double lat, double lon, double lat0) {
        double x = Math.toRadians(lon) * Math.cos(Math.toRadians(lat0)) * R;
        double y = Math.toRadians(lat) * R;
        return new double[] { x, y };
    }

    /**
     * Distance (m) from P to segment A-B, plus the clamped projection parameter t in
     * [0, 1]. Returned as {@code {distance, t}}.
     */
    public static double[] pointToSegmentM(double plat, double plon,
                                           double alat, double alon,
                                           double blat, double blon) {
        double lat0 = (alat + blat) / 2;
        double[] p = xy(plat, plon, lat0);
        double[] a = xy(alat, alon, lat0);
        double[] b = xy(blat, blon, lat0);

        double dx = b[0] - a[0];
        double dy = b[1] - a[1];
        double seg2 = dx * dx + dy * dy;

        double t;
        if (seg2 == 0) {
            t = 0.0;
        } else {
            t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg2;
            t = Math.max(0.0, Math.min(1.0, t));
        }
        double cx = a[0] + t * dx;
        double cy = a[1] + t * dy;
        return new double[] { Math.hypot(p[0] - cx, p[1] - cy), t };
    }

    private static double[] interp(double[] a, double[] b, double t) {
        return new double[] { a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t };
    }

    /**
     * The sub-polyline between two fractions of a path's length.
     *
     * <p>Both cut points are interpolated onto the line, so the result begins and ends
     * exactly where asked rather than at the nearest vertex. Used to trim a bus leg down
     * to the part a passenger actually rides when they board or alight at an unofficial
     * stop partway along it.
     */
    public static List<double[]> slicePath(double[][] path, double startF, double endF) {
        List<double[]> out = new ArrayList<>();
        if (path == null || path.length == 0) {
            return out;
        }
        if (path.length < 2) {
            out.add(path[0].clone());
            return out;
        }
        if (startF <= 0.0 && endF >= 1.0) {
            for (double[] p : path) {
                out.add(p.clone());
            }
            return out;
        }

        startF = Math.max(0.0, Math.min(1.0, startF));
        endF = Math.max(0.0, Math.min(1.0, endF));
        if (endF <= startF) {
            return out;
        }

        double[] segLen = new double[path.length - 1];
        double total = 0.0;
        for (int i = 0; i < path.length - 1; i++) {
            segLen[i] = haversineM(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1]);
            total += segLen[i];
        }
        if (total <= 0) {
            out.add(path[0].clone());
            return out;
        }

        double startM = startF * total;
        double endM = endF * total;
        double cum = 0.0;
        for (int i = 0; i < segLen.length; i++) {
            double length = segLen[i];
            double next = cum + length;
            // Skip segments entirely before the start or after the end of the window.
            if (next < startM || cum > endM || length <= 0) {
                cum = next;
                continue;
            }
            double[] a = path[i];
            double[] b = path[i + 1];
            double t0 = Math.max(0.0, (startM - cum) / length);
            double t1 = Math.min(1.0, (endM - cum) / length);
            double[] p0 = t0 <= 0 ? a.clone() : interp(a, b, t0);
            double[] p1 = t1 >= 1 ? b.clone() : interp(a, b, t1);
            if (out.isEmpty()) {
                out.add(p0);
            }
            if (!samePoint(out.get(out.size() - 1), p1)) {
                out.add(p1);
            }
            cum = next;
        }
        return out;
    }

    static boolean samePoint(double[] a, double[] b) {
        return a.length == b.length && a[0] == b[0] && a[1] == b[1];
    }

    /**
     * Nearest distance (m) from P to the polyline, and the fraction f in [0, 1] along it
     * (along-path distance to the closest projection divided by total length).
     * Returned as {@code {distance, fraction}}.
     */
    public static double[] locateOnPath(double[][] path, Double lengthM, double plat, double plon) {
        if (path == null || path.length == 0) {
            return new double[] { Double.POSITIVE_INFINITY, 0.0 };
        }
        if (path.length < 2) {
            return new double[] { haversineM(plat, plon, path[0][0], path[0][1]), 0.0 };
        }

        double total = lengthM == null ? 0.0 : lengthM;
        if (total == 0.0) {
            for (int i = 0; i < path.length - 1; i++) {
                total += haversineM(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1]);
            }
        }

        double bestD = Double.POSITIVE_INFINITY;
        double bestAlong = 0.0;
        double cum = 0.0;
        for (int i = 0; i < path.length - 1; i++) {
            double[] a = path[i];
            double[] b = path[i + 1];
            double segLen = haversineM(a[0], a[1], b[0], b[1]);
            double[] dt = pointToSegmentM(plat, plon, a[0], a[1], b[0], b[1]);
            if (dt[0] < bestD) {
                bestD = dt[0];
                bestAlong = cum + dt[1] * segLen;
            }
            cum += segLen;
        }

        double f = total > 0 ? bestAlong / total : 0.0;
        return new double[] { bestD, Math.max(0.0, Math.min(1.0, f)) };
    }
}
