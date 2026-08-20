package za.co.commuttr.api.web;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import za.co.commuttr.api.dto.CatalogDtos.HealthResponse;
import za.co.commuttr.api.dto.CatalogDtos.RouteDetailResponse;
import za.co.commuttr.api.dto.CatalogDtos.RoutesResponse;
import za.co.commuttr.api.dto.CatalogDtos.TimetableDetailResponse;
import za.co.commuttr.api.dto.StopDtos.AreasResponse;
import za.co.commuttr.api.service.CatalogService;

/** Read-only catalogue endpoints, on the same paths the FastAPI service served. */
@RestController
@RequestMapping("/api")
public class CatalogController {

    private final CatalogService catalog;

    public CatalogController(CatalogService catalog) {
        this.catalog = catalog;
    }

    @GetMapping("/health")
    public HealthResponse health() {
        return catalog.health();
    }

    @GetMapping("/routes")
    public RoutesResponse listRoutes(@RequestParam(required = false) String q,
                                     @RequestParam(required = false) String letter) {
        return catalog.listRoutes(q, letter);
    }

    @GetMapping("/routes/{routeId}")
    public RouteDetailResponse getRoute(@PathVariable Integer routeId) {
        return catalog.getRoute(routeId);
    }

    @GetMapping("/timetables/{timetableId}")
    public TimetableDetailResponse getTimetable(@PathVariable Integer timetableId) {
        return catalog.getTimetable(timetableId);
    }

    /**
     * Route-endpoint area names that are not published stops (KRAAIFONTEIN, NYANGA,
     * PHILIPPI and friends). Surfaced in search so an area is a first-class endpoint.
     */
    @GetMapping("/areas")
    public AreasResponse areas() {
        return catalog.areas();
    }
}
