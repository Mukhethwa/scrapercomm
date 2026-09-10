/**
 * Whether the rider's own point is a row the timetable does not already have.
 *
 * Its own module because it takes no data from anywhere - a name, a label and a time -
 * and can therefore be run and checked on its own. See pins.test.ts.
 */
/**
 * Whether the breakdown should show a row for the rider's own point, and what it says.
 *
 * A place is not always a boarding point, and the app had it as always. The planner
 * anchors a pin two ways: on a ROAD LEG, where the bus passes a point between two stops
 * and the rider stands there - and on a STOP within walking distance, where they walk to
 * something the timetable names and board it like anybody else. The second one arrived
 * when places gained a walk to the nearest stop, and nothing here was told.
 *
 * So Kraaifontein to Woodstock drew
 *
 *     Kraaifontein (your stop)  get on here   after 05:10
 *     CAPE GATE                                    05:10
 *
 * - the same minute twice, once invented and once printed, with "get on here" on the row
 * that is not a stop and no tag on the row that is. The rider walks 1.9km to CAPE GATE
 * and boards there; the timetable already had the answer.
 *
 * The API says which case it is in board_label: "between BEACON VALLEY and TOWN CENTRE"
 * for a road leg, a bare stop name for a walk. Only the first is a row the timetable does
 * not already contain, and only the first gets one.
 *
 * A train is neither. It is caught at a station and the place is where the walk starts,
 * which is why the ends were suppressed for rail before any of this.
 */
export function pinEnd(
  { end, label, operatorKind, time, approx }: {
    end?: { kind: 'stop' | 'pin'; name: string } | null
    label?: string
    operatorKind?: string
    time?: string
    approx?: boolean
  },
): { name: string; time?: string; approx: boolean } | null {
  if (!end || end.kind !== 'pin') return null
  if (operatorKind === 'train') return null
  // No label to judge by - a journey saved before the app recorded one. Falling back to
  // "show it" would put the invented row back, so it falls back to the timetable, which
  // is never wrong about its own stops.
  if (!label || !label.startsWith('between ')) return null
  return { name: end.name, time, approx: approx ?? true }
}
