package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.Trip;

import java.util.List;

@Repository
public interface TripRepository extends JpaRepository<Trip, Integer> {

    /** GET /api/timetables/{id} -> schedules[].trips[]. */
    List<Trip> findByScheduleIdOrderByTripIndexAsc(Integer scheduleId);
}
