package za.co.commuttr.api;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import za.co.commuttr.api.service.ApiFormat;
import za.co.commuttr.api.service.DayTypes;
import za.co.commuttr.api.service.GeoUtils;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/** The value formatting and geo maths must agree with the Python originals. */
class ApiFormatAndGeoTest {

    @Test
    @DisplayName("times render as HH:MM and nulls stay null")
    void formatsTimes() {
        assertThat(ApiFormat.time(LocalTime.of(6, 5))).isEqualTo("06:05");
        assertThat(ApiFormat.time(LocalTime.of(23, 59))).isEqualTo("23:59");
        assertThat(ApiFormat.time(null)).isNull();
    }

    @Test
    void formatsDatesAsIsoOrNull() {
        assertThat(ApiFormat.date(LocalDate.of(2026, 6, 22))).isEqualTo("2026-06-22");
        assertThat(ApiFormat.date(null)).isNull();
    }

    @Test
    void convertsTimesToMinutesPastMidnight() {
        assertThat(ApiFormat.minutes(LocalTime.of(6, 5))).isEqualTo(365);
        assertThat(ApiFormat.minutes(null)).isNull();
    }

    @Test
    @DisplayName("interpolated minutes render as a clock time, wrapping past midnight")
    void rendersMinutesAsClock() {
        assertThat(ApiFormat.minutesToClock(365)).isEqualTo("06:05");
        assertThat(ApiFormat.minutesToClock(365.4)).isEqualTo("06:05");
        assertThat(ApiFormat.minutesToClock(1500)).isEqualTo("01:00"); // 25:00 wraps
        assertThat(ApiFormat.minutesToClock(null)).isNull();
    }

    @Test
    @DisplayName("rounding is half-to-even, matching Python's round()")
    void roundsLikePython() {
        assertThat(ApiFormat.roundTo(2.25, 1)).isEqualTo(2.2);
        assertThat(ApiFormat.roundTo(2.35, 1)).isEqualTo(2.4);
        assertThat(ApiFormat.roundToLong(0.5)).isEqualTo(0);
        assertThat(ApiFormat.roundToLong(1.5)).isEqualTo(2);
        assertThat(ApiFormat.roundToLong(2.5)).isEqualTo(2);
    }

    @Test
    void ordersDayTypesForCommuters() {
        assertThat(DayTypes.order("WEEKDAY")).isZero();
        assertThat(DayTypes.order("PUBLIC_HOLIDAY")).isEqualTo(3);
        assertThat(DayTypes.order("OTHER")).isEqualTo(9);
        assertThat(DayTypes.order(null)).isEqualTo(9);
    }

    @Test
    @DisplayName("haversine matches the known Cape Town CBD to Bellville distance")
    void measuresDistance() {
        // Cape Town station to Bellville station, roughly 20 km apart.
        double d = GeoUtils.haversineM(-33.9224, 18.4256, -33.9022, 18.6295);
        assertThat(d).isCloseTo(19_200, within(600.0));
        assertThat(GeoUtils.haversineM(-33.9224, 18.4256, -33.9224, 18.4256)).isZero();
    }

    @Test
    @DisplayName("a point beside a polyline reports its distance and how far along it sits")
    void locatesPointOnPath() {
        // A due-east leg of two segments; the probe sits just north of the midpoint.
        double[][] path = { { -33.9200, 18.4200 }, { -33.9200, 18.4300 }, { -33.9200, 18.4400 } };
        double[] located = GeoUtils.locateOnPath(path, null, -33.9205, 18.4300);

        assertThat(located[0]).isCloseTo(55.0, within(10.0)); // ~0.0005 degrees of latitude
        assertThat(located[1]).isCloseTo(0.5, within(0.01));  // halfway along
    }

    @Test
    @DisplayName("slicePath keeps only the ridden part, cutting exactly at the fraction")
    void slicesPathToTheRiddenPortion() {
        double[][] path = { { 0, 0 }, { 0, 0.01 }, { 0, 0.02 } };

        // The whole leg is returned untouched when nothing is trimmed.
        assertThat(GeoUtils.slicePath(path, 0.0, 1.0)).hasSize(3);

        // Boarding halfway starts the line at the midpoint, not at the nearest vertex.
        List<double[]> head = GeoUtils.slicePath(path, 0.5, 1.0);
        assertThat(head.get(0)[1]).isCloseTo(0.01, within(1e-6));
        assertThat(head.get(head.size() - 1)[1]).isCloseTo(0.02, within(1e-9));

        // Alighting halfway ends it there.
        List<double[]> tail = GeoUtils.slicePath(path, 0.0, 0.5);
        assertThat(tail.get(0)[1]).isCloseTo(0.0, within(1e-9));
        assertThat(tail.get(tail.size() - 1)[1]).isCloseTo(0.01, within(1e-6));
    }

    @Test
    @DisplayName("board and alight on the same leg trims both ends of one segment")
    void slicesBothEndsOfASingleSegment() {
        double[][] leg = { { 0, 0 }, { 0, 0.02 } };
        List<double[]> out = GeoUtils.slicePath(leg, 0.25, 0.75);

        assertThat(out.get(0)[1]).isCloseTo(0.005, within(1e-6));
        assertThat(out.get(out.size() - 1)[1]).isCloseTo(0.015, within(1e-6));
        // Every cut point stays on the road rather than wandering off it.
        assertThat(out).allSatisfy(p -> assertThat(p[0]).isCloseTo(0.0, within(1e-9)));
    }

    @Test
    void slicePathHandlesDegenerateInput() {
        assertThat(GeoUtils.slicePath(new double[0][], 0.2, 0.8)).isEmpty();
        assertThat(GeoUtils.slicePath(new double[][] { { 1, 2 } }, 0.2, 0.8)).hasSize(1);
        // An inverted window yields nothing rather than a reversed line.
        assertThat(GeoUtils.slicePath(new double[][] { { 0, 0 }, { 0, 0.01 } }, 0.8, 0.2))
                .isEmpty();
    }

    @Test
    void handlesDegeneratePaths() {
        assertThat(GeoUtils.locateOnPath(new double[0][], null, -33.9, 18.4)[0])
                .isEqualTo(Double.POSITIVE_INFINITY);
        assertThat(GeoUtils.locateOnPath(new double[][] { { -33.9, 18.4 } }, null, -33.9, 18.4)[1])
                .isZero();
    }
}
