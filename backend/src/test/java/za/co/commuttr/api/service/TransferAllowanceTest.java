package za.co.commuttr.api.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import za.co.commuttr.api.dto.PlanDtos.FareDto;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * How many changes a fare's transfer allowance covers, when it states one and when it
 * does not.
 *
 * <p>9,273 of the 23,805 fares in this database leave the column null - every Metrorail
 * one, priced by distance band, and many of Golden Arrow's. The lookup was a
 * {@code Map.of}, which throws on a null key rather than returning the default, so a
 * journey with a change whose two ends happened to have a through fare of that kind
 * answered 500 and the screen showed nothing at all.
 *
 * <p>It went unnoticed because it needed the two ends to have a through fare AND that
 * fare to state no allowance, which no journey the app usually reached did - until
 * connections started starting from the nearest stop rather than the nearest station.
 *
 * <p>Here rather than against the running app: the pairs that reach it are the slow ones,
 * and a test that takes four minutes to skip guards nothing.
 */
class TransferAllowanceTest {

    private static FareDto withTransfers(String transfers) {
        return new FareDto("Z1", 1000, null, null, null, transfers,
                "exact", "A", "B", false, null, null, null, null, null);
    }

    @Test
    @DisplayName("a stated allowance is read")
    void readsAStatedAllowance() {
        assertThat(ConnectionService.changesCovered(withTransfers("Zero"))).isZero();
        assertThat(ConnectionService.changesCovered(withTransfers("One"))).isEqualTo(1);
        assertThat(ConnectionService.changesCovered(withTransfers("Two"))).isEqualTo(2);
    }

    @Test
    @DisplayName("saying nothing about transfers covers no change, and does not throw")
    void treatsSilenceAsNoAllowance() {
        assertThatCode(() -> ConnectionService.changesCovered(withTransfers(null)))
                .doesNotThrowAnyException();
        assertThat(ConnectionService.changesCovered(withTransfers(null))).isZero();
        assertThat(ConnectionService.changesCovered(null)).isZero();
    }

    @Test
    @DisplayName("a wording nobody has seen before covers no change either")
    void treatsAnUnknownWordingAsNoAllowance() {
        assertThat(ConnectionService.changesCovered(withTransfers("Three"))).isZero();
        assertThat(ConnectionService.changesCovered(withTransfers(""))).isZero();
    }
}
