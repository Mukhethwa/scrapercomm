package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.TimetableNote;
import za.co.commuttr.api.repo.projection.Projections.NoteRow;

import java.util.List;

@Repository
public interface TimetableNoteRepository extends JpaRepository<TimetableNote, Integer> {

    /** GET /api/timetables/{id} -> notes[]. */
    List<NoteRow> findByTimetableIdOrderByCodeAsc(Integer timetableId);
}
