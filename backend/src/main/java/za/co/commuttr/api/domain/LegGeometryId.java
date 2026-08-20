package za.co.commuttr.api.domain;

import java.io.Serializable;
import java.util.Objects;

/** Composite key of leg_geometry (from_stop_id, to_stop_id). */
public class LegGeometryId implements Serializable {

    private Integer fromStopId;
    private Integer toStopId;

    protected LegGeometryId() { }

    public LegGeometryId(Integer fromStopId, Integer toStopId) {
        this.fromStopId = fromStopId;
        this.toStopId = toStopId;
    }

    public Integer getFromStopId() { return fromStopId; }
    public Integer getToStopId() { return toStopId; }

    @Override
    public boolean equals(Object o) {
        if (this == o) {
            return true;
        }
        if (!(o instanceof LegGeometryId other)) {
            return false;
        }
        return Objects.equals(fromStopId, other.fromStopId)
                && Objects.equals(toStopId, other.toStopId);
    }

    @Override
    public int hashCode() {
        return Objects.hash(fromStopId, toStopId);
    }
}
