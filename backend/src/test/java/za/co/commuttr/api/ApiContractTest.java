package za.co.commuttr.api;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.HttpStatus;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import za.co.commuttr.api.dto.CatalogDtos.RouteSummaryDto;
import za.co.commuttr.api.dto.CatalogDtos.RoutesResponse;
import za.co.commuttr.api.dto.JourneyDtos.JourneyDepartureDto;
import za.co.commuttr.api.dto.JourneyDtos.JourneyOptionDto;
import za.co.commuttr.api.dto.JourneyDtos.JourneysResponse;
import za.co.commuttr.api.dto.JourneyDtos.SegmentStopDto;
import za.co.commuttr.api.dto.PlanDtos.PlanDepartureDto;
import za.co.commuttr.api.dto.PlanDtos.PlanOptionDto;
import za.co.commuttr.api.dto.PlanDtos.PlanResponse;
import za.co.commuttr.api.dto.PlanDtos.PlanSegmentStopDto;
import za.co.commuttr.api.dto.StopDtos.PinDto;
import za.co.commuttr.api.dto.StopDtos.StopDto;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionDto;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionLegDto;
import za.co.commuttr.api.dto.ConnectionDtos.ConnectionsResponse;
import za.co.commuttr.api.service.CatalogService;
import za.co.commuttr.api.service.ConnectionService;
import za.co.commuttr.api.service.GeocodeService;
import za.co.commuttr.api.service.JourneyService;
import za.co.commuttr.api.service.PlannerService;
import za.co.commuttr.api.service.StopService;
import za.co.commuttr.api.web.ApiException;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Locks down the wire contract the React client already depends on: snake_case keys,
 * FastAPI's {@code {"detail": ...}} error envelope, and its status codes.
 */
@WebMvcTest
class ApiContractTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean CatalogService catalog;
    @MockitoBean StopService stops;
    @MockitoBean JourneyService journeys;
    @MockitoBean PlannerService planner;
    @MockitoBean GeocodeService geocode;
    @MockitoBean ConnectionService connections;

    @Test
    @DisplayName("GET /api/routes keeps letter_group and timetable_count in snake_case")
    void routesKeepSnakeCaseKeys() throws Exception {
        given(catalog.listRoutes(any(), any())).willReturn(new RoutesResponse(List.of(
                new RouteSummaryDto(7, "AIRPORT IND-BELLVILLE", "AIRPORT IND", "BELLVILLE", "A", 4L))));

        mvc.perform(get("/api/routes").param("q", "bell"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.routes[0].id").value(7))
                .andExpect(jsonPath("$.routes[0].letter_group").value("A"))
                .andExpect(jsonPath("$.routes[0].timetable_count").value(4))
                .andExpect(jsonPath("$.routes[0].letterGroup").doesNotExist());
    }

    @Test
    @DisplayName("a missing route answers 404 with FastAPI's detail envelope")
    void missingRouteIsFastApiShaped() throws Exception {
        given(catalog.getRoute(anyInt())).willThrow(ApiException.notFound("route not found"));

        mvc.perform(get("/api/routes/999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.detail").value("route not found"));
    }

    @Test
    @DisplayName("GET /api/journeys renders from/to verbatim and board_time in snake_case")
    void journeysResponseShape() throws Exception {
        JourneyOptionDto option = new JourneyOptionDto(
                "004401", "NYANGA - AIRPORT IND - BELLVILLE", "WEEKDAY", "MONDAYS TO FRIDAYS",
                List.of(11, 12),
                List.of(new SegmentStopDto("NYANGA TERM", -33.98, 18.58, 0)),
                List.of(new JourneyDepartureDto("06:05", "0605", "TIME", null, "06:47", "0647", "TIME")));
        given(journeys.journeys(anyInt(), anyInt())).willReturn(new JourneysResponse(
                new StopDto(1, "NYANGA TERM", -33.98, 18.58),
                new StopDto(2, "BELLVILLE", -33.90, 18.62),
                List.of(option)));

        mvc.perform(get("/api/journeys").param("from", "1").param("to", "2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.from.id").value(1))
                .andExpect(jsonPath("$.to.name").value("BELLVILLE"))
                .andExpect(jsonPath("$.options[0].timetable_number").value("004401"))
                .andExpect(jsonPath("$.options[0].route_label").exists())
                .andExpect(jsonPath("$.options[0].day_type").value("WEEKDAY"))
                .andExpect(jsonPath("$.options[0].timetable_ids[1]").value(12))
                .andExpect(jsonPath("$.options[0].segment_stops[0].stop_sequence").value(0))
                .andExpect(jsonPath("$.options[0].departures[0].board_time").value("06:05"))
                .andExpect(jsonPath("$.options[0].departures[0].note_code").doesNotExist());
    }

    @Test
    @DisplayName("a missing required query parameter answers 422, as Pydantic did")
    void missingQueryParamIsUnprocessable() throws Exception {
        mvc.perform(get("/api/journeys").param("from", "1"))
                .andExpect(status().is(HttpStatus.UNPROCESSABLE_ENTITY.value()))
                .andExpect(jsonPath("$.detail[0].type").value("missing"))
                .andExpect(jsonPath("$.detail[0].loc[0]").value("query"))
                .andExpect(jsonPath("$.detail[0].loc[1]").value("to"));
    }

    @Test
    @DisplayName("an unparseable query parameter also answers 422")
    void badQueryParamIsUnprocessable() throws Exception {
        mvc.perform(get("/api/journeys").param("from", "abc").param("to", "2"))
                .andExpect(status().is(HttpStatus.UNPROCESSABLE_ENTITY.value()))
                .andExpect(jsonPath("$.detail[0].type").value("int_parsing"));
    }

    @Test
    @DisplayName("GET /api/plan without any endpoint answers 400 with the original message")
    void planWithoutEndpointsIsBadRequest() throws Exception {
        mvc.perform(get("/api/plan"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.detail")
                        .value("provide from (stop id) or from_lat/from_lon, and to likewise"));
    }

    @Test
    @DisplayName("GET /api/connections keeps snake_case keys and nests legs in travel order")
    void connectionsResponseShape() throws Exception {
        ConnectionLegDto leg1 = new ConnectionLegDto(
                24696, "MALMESBURY", -33.45, 18.73, 101, "CAPE TOWN", -33.92, 18.42,
                "MALMESBURY - KILLARNEY - CAPE TOWN", "013501", "07:45", "10:00", 465, 600,
                14230, 4, 0, 8);
        ConnectionLegDto leg2 = new ConnectionLegDto(
                101, "CAPE TOWN", -33.92, 18.42, 3370, "BUH REIN", -33.82, 18.71,
                "CAPE TOWN - NORTHPINE - KRAAIFONTEIN", "001501", "14:50", "via", 890, null,
                13987, 0, 0, 6);
        given(connections.connections(anyInt(), anyInt())).willReturn(new ConnectionsResponse(
                new StopDto(24696, "MALMESBURY", -33.45, 18.73),
                new StopDto(3370, "BUH REIN", -33.82, 18.71),
                2,
                List.of(new ConnectionDto("WEEKDAY", List.of("CAPE TOWN"),
                        List.of(leg1, leg2), 290, 425))));

        mvc.perform(get("/api/connections").param("from", "24696").param("to", "3370"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.from.name").value("MALMESBURY"))
                .andExpect(jsonPath("$.legs_required").value(2))
                .andExpect(jsonPath("$.connections[0].change_at[0]").value("CAPE TOWN"))
                .andExpect(jsonPath("$.connections[0].total_minutes").value(425))
                .andExpect(jsonPath("$.connections[0].wait_minutes").value(290))
                .andExpect(jsonPath("$.connections[0].legs[0].from_name").value("MALMESBURY"))
                .andExpect(jsonPath("$.connections[0].legs[0].board_raw").value("07:45"))
                .andExpect(jsonPath("$.connections[0].legs[1].to_name").value("BUH REIN"))
                // an unpublished arrival stays the literal cell rather than becoming null
                .andExpect(jsonPath("$.connections[0].legs[1].arrive_raw").value("via"))
                .andExpect(jsonPath("$.connections[0].legs[1].schedule_id").value(13987))
                // Each leg carries its own timetable number; the planner shows it per leg.
                .andExpect(jsonPath("$.connections[0].legs[0].timetable_number").value("013501"))
                .andExpect(jsonPath("$.connections[0].legs[1].timetable_number").value("001501"));
    }

    @Test
    @DisplayName("nothing reachable answers 200 with legs_required null, not an error")
    void connectionsWhenUnreachable() throws Exception {
        given(connections.connections(anyInt(), anyInt())).willReturn(new ConnectionsResponse(
                new StopDto(24696, "MALMESBURY", -33.45, 18.73),
                new StopDto(9099, "KHAYELITSHA", -34.0, 18.65),
                null, List.of()));

        mvc.perform(get("/api/connections").param("from", "24696").param("to", "9099"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.legs_required").doesNotExist())
                .andExpect(jsonPath("$.connections").isEmpty());
    }

    @Test
    @DisplayName("a wrong HTTP method keeps its 405, reshaped into the detail envelope")
    void wrongMethodKeepsItsStatus() throws Exception {
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                        .post("/api/health"))
                .andExpect(status().isMethodNotAllowed())
                .andExpect(jsonPath("$.detail").value("Method Not Allowed"));
    }

    @Test
    @DisplayName("a pin endpoint renders as {kind: pin}; exact minutes stay integers")
    void planRendersPinsAndNumberShapes() throws Exception {
        PlanOptionDto option = new PlanOptionDto(
                "004401", "NYANGA - BELLVILLE", "WEEKDAY", "MONDAYS TO FRIDAYS",
                List.of(new PlanSegmentStopDto(3, "NYANGA TERM", -33.98, 18.58, 0)),
                List.of(new double[] { -33.98, 18.58 }, new double[] { -33.90, 18.62 }),
                List.of(new PlanDepartureDto("0605", false, 365, "06:47", true, 407.5, 88, 2, 0, 6)),
                false, true, "NYANGA TERM", "near A–B");
        given(planner.plan(any(), any())).willReturn(new PlanResponse(
                new StopDto(3, "NYANGA TERM", -33.98, 18.58), PinDto.of(-33.90, 18.62),
                List.of(option)));

        mvc.perform(get("/api/plan").param("from", "3").param("to_lat", "-33.90").param("to_lon", "18.62"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.from.id").value(3))
                .andExpect(jsonPath("$.to.kind").value("pin"))
                .andExpect(jsonPath("$.options[0].road_path[0][0]").value(-33.98))
                .andExpect(jsonPath("$.options[0].board_approx").value(false))
                .andExpect(jsonPath("$.options[0].alight_label").value("near A–B"))
                .andExpect(jsonPath("$.options[0].segment_stops[0].stop_id").value(3))
                // an exact stop keeps an integer; an interpolated pin keeps its fraction
                .andExpect(jsonPath("$.options[0].departures[0].board_minutes").value(365))
                .andExpect(jsonPath("$.options[0].departures[0].arrive_minutes").value(407.5))
                .andExpect(jsonPath("$.options[0].departures[0].from_seq").value(0))
                .andExpect(jsonPath("$.options[0].departures[0].to_seq").value(6));
    }
}
