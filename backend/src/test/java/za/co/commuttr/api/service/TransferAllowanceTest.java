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

    @Test
    @DisplayName("a train journey with a change is priced as one ticket for the distance by rail")
    void pricesTrainsByTheBandOfTheWholeDistance() {
        // Kraaifontein to Kalk Bay changing at Woodstock: 27.3 km and 30.1 km, one Zone 3 ticket.
        assertThat(ConnectionService.prasaBand(27.3 + 30.1)).containsExactly(3, 1400, 8000, 25000);
        assertThat(ConnectionService.prasaBand(15.0)).containsExactly(1, 1000, 6000, 18000);
        assertThat(ConnectionService.prasaBand(15.1)[0]).isEqualTo(2);
        assertThat(ConnectionService.prasaBand(40.0)[0]).isEqualTo(2);
        assertThat(ConnectionService.prasaBand(61.3)).containsExactly(4, 1500, 9000, 28000);
    }

    @Test
    @DisplayName("the last leg of a journey with a change keeps its published arrival")
    void readsTheArrivalFromTheCell() {
        assertThat(ConnectionService.minutesOf("08:59:00")).isEqualTo(539);
        assertThat(ConnectionService.minutesOf("16:30a")).isEqualTo(990);
        assertThat(ConnectionService.minutesOf("6:05")).isEqualTo(365);
        assertThat(ConnectionService.minutesOf("via")).isNull();
        assertThat(ConnectionService.minutesOf(null)).isNull();
    }

    @Test
    @DisplayName("a MyCiTi journey with a change is one fare for its whole distance")
    void pricesMycitiByTheBandOfTheWholeDistance() {
        // Table View to Kloof Nek, changing at Civic Centre: the City charges 20-30km.
        assertThat(ConnectionService.mycitiBand(16.4 + 5.2)).containsExactly(3450, 2950);
        assertThat(ConnectionService.mycitiBandLabel(21.6)).isEqualTo("20-30km");
        assertThat(ConnectionService.mycitiBand(5.0)).containsExactly(1950, 1500);
        assertThat(ConnectionService.mycitiBandLabel(5.01)).isEqualTo("5-10km");
        assertThat(ConnectionService.mycitiBandLabel(75)).isEqualTo("60km+");
    }
}
