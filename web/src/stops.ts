/**
 * How many stops are on a ride, in the words a rider uses.
 *
 * The count excludes the two ends: somebody asking "how many stops" means the ones they
 * sit through, not the one they get on at. Zero of those is worth saying plainly rather
 * than as "0 stops", because a bus that goes straight there is the best answer on the
 * board and should read like one.
 */
export function stopLabel(n: number | null | undefined): string | null {
  if (n == null) return null
  if (n === 0) return 'non-stop'
  return n === 1 ? '1 stop' : `${n} stops`
}
