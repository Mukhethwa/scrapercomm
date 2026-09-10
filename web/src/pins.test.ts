/**
 * When the rider's own place is a row of the trip, and when it is not.
 *
 *     node --test src/pins.test.ts        (or: npm test)
 *
 * Same screenshot as times.test.ts, one row higher up:
 *
 *     Kraaifontein (your stop)  get on here   after 05:10
 *     CAPE GATE                                    05:10
 *
 * Two rows, one minute, and "get on here" on the row that is not a stop. The rider walks
 * 1.9km to CAPE GATE and boards it like anybody else - the timetable already had the
 * answer, and the app put an invented row above it.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { pinEnd } from './pins.ts'

const PIN = { kind: 'pin' as const, name: 'Kraaifontein' }
const STOP = { kind: 'stop' as const, name: 'CAPE GATE' }

test('a point on the road between two stops is a row of its own', () => {
  assert.deepEqual(
    pinEnd({ end: PIN, label: 'between N1 FREEWAY and CAPE TOWN', operatorKind: 'bus',
             time: 'by 06:30', approx: true }),
    { name: 'Kraaifontein', time: 'by 06:30', approx: true },
  )
})

test('walking to a named stop is not', () => {
  // The bug: board_label is the stop itself, so the timetable's own CAPE GATE row is the
  // boarding point and nothing needs inventing.
  assert.equal(
    pinEnd({ end: PIN, label: 'CAPE GATE', operatorKind: 'bus',
             time: '05:10', approx: false }),
    null,
  )
})

test('a published time on a pin row stays published', () => {
  // It was hardcoded approximate, so a real 05:10 arrived on screen as "after 05:10".
  const row = pinEnd({ end: PIN, label: 'between A and B', operatorKind: 'bus',
                       time: '05:10', approx: false })
  assert.equal(row?.approx, false)
})

test('a stop the rider chose themselves is never a pin', () => {
  assert.equal(
    pinEnd({ end: STOP, label: 'between A and B', operatorKind: 'bus', time: '05:10' }),
    null,
  )
  assert.equal(pinEnd({ end: null, label: 'between A and B' }), null)
  assert.equal(pinEnd({}), null)
})

test('a train is caught at a station, never at a place', () => {
  assert.equal(
    pinEnd({ end: PIN, label: 'between A and B', operatorKind: 'train', time: '05:10' }),
    null,
  )
})

test('a journey saved before the label was recorded falls back to the timetable', () => {
  // A missing row is a smaller wrong than an invented one.
  assert.equal(pinEnd({ end: PIN, operatorKind: 'bus', time: '05:10' }), null)
})

test('an unknown time still yields a row, so the rider sees where they get off', () => {
  const row = pinEnd({ end: PIN, label: 'between A and B', operatorKind: 'bus' })
  assert.deepEqual(row, { name: 'Kraaifontein', time: undefined, approx: true })
})
