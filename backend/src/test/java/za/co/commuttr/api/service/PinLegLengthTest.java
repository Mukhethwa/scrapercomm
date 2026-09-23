package za.co.commuttr.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import za.co.commuttr.api.dto.PlanDtos.LegHitDto;
import za.co.commuttr.api.repo.LegGeometryRepository;
import za.co.commuttr.api.repo.projection.Projections.LegGeometryRow;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;

/**
 * Which roads count as somewhere a rider can be told to stand.
 *
 * <p>A pin boards a rider "between A and B" on the road a vehicle drives between two
 * consecutive stops. That is true of a short hop through a suburb and false of a long run
 * across the metro: Woodstock to Steenberg offered a boarding "between ROUTE 2 and HARARE"
 * on a leg sweeping 34 km, and a sweep of 25 random place pairs found 16 such boardings in
 * 27. 464 of the network's 2,775 legs are longer than {@link PlannerService#MAX_PIN_LEG_M}.
 *
 * <p>Against stub geometry rather than the database: the rule is about the length of a leg
 * and nothing else, and a test that needs Postgres loaded to say so guards less.
 */
class PinLegLengthTest {

    /** Woodstock, and a road running east from it. */
    private static final double LAT = -33.9276;
    private static final double LON = 18.4451;
    private static final String PATH = "[[-33.9276,18.4451],[-33.9280,18.4470]]";

    private static LegGeometryRow leg(int fromStopId, int toStopId, Double lengthM) {
        LegGeometryRow row = mock(LegGeometryRow.class);
        given(row.getFromStopId()).willReturn(fromStopId);
        given(row.getToStopId()).willReturn(toStopId);
        given(row.getPath()).willReturn(PATH);
        given(row.getLengthM()).willReturn(lengthM);
        return row;
    }

    private static PlannerService plannerOver(LegGeometryRow... rows) {
        LegGeometryRepository legs = mock(LegGeometryRepository.class);
        given(legs.findNearPoint(anyDouble(), anyDouble(), anyDouble())).willReturn(List.of(rows));
        return new PlannerService(null, null, null, null, legs, new ObjectMapper(), null);
    }

    @Test
    @DisplayName("a long leg is no place to catch a bus, a short one is")
    void dropsTheLongLeg() {
        PlannerService planner = plannerOver(
                leg(1, 2, 500.0),
                leg(3, 4, 30_000.0));

        List<LegHitDto> capped = planner.locatePoint(
                LAT, LON, PlannerService.DEFAULT_THRESHOLD_M, PlannerService.MAX_PIN_LEG_M);

        assertThat(capped).hasSize(1);
        assertThat(capped.getFirst().fromStopId()).isEqualTo(1);
    }

    @Test
    @DisplayName("without a cap both legs still match, so nothing else changed")
    void keepsBothWhenUncapped() {
        PlannerService planner = plannerOver(
                leg(1, 2, 500.0),
                leg(3, 4, 30_000.0));

        assertThat(planner.locatePoint(LAT, LON, PlannerService.DEFAULT_THRESHOLD_M)).hasSize(2);
    }

    @Test
    @DisplayName("a leg of unknown length is kept")
    void keepsALegWithNoLength() {
        PlannerService planner = plannerOver(leg(5, 6, null));

        assertThat(planner.locatePoint(
                LAT, LON, PlannerService.DEFAULT_THRESHOLD_M, PlannerService.MAX_PIN_LEG_M))
                .hasSize(1);
    }
}
