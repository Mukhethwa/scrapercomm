package za.co.commuttr.api.repo;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import za.co.commuttr.api.domain.SearchAnalyticsOption;

@Repository
public interface SearchAnalyticsOptionRepository extends JpaRepository<SearchAnalyticsOption, Long> {
}
