/**
 * Which card owns the opened departure.
 *
 *     node --test src/results.test.ts        (or: npm test)
 *
 * Mowbray to Kraaifontein, opening the 04:50 train, produced TWO breakdowns: one under
 * Metrorail, and the same one again under Golden Arrow Buses - under a heading that reads
 * DIRECT BUS, over a list of stops no bus calls at, at times no bus keeps.
 *
 * The breakdown was built once from the open departure and handed to every card, and
 * every card drew it, because none of them asked whether the departure was theirs.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  blockKey, onlyOperator, ownsOpenDeparture, type DepartureBlock,
} from './results.ts'

/** Just the two fields identity is made of; the rest of a block is not consulted. */
function block(optionIndex: number, departureIndex: number): DepartureBlock {
  return { optionIndex, departureIndex } as DepartureBlock
}

// Metrorail holds option 0 (four trains); Golden Arrow holds options 1 and 2.
const TRAINS = [block(0, 0), block(0, 1), block(0, 2), block(0, 3)]
const BUSES = [block(1, 0), block(1, 1), block(2, 0)]

test('a departure is identified by its option and its place in it', () => {
  assert.equal(blockKey(0, 0), '0-0')
  assert.equal(blockKey(12, 3), '12-3')
  // Written out by hand in four places before this; they agreed, and nothing made them.
  assert.equal(blockKey(1, 11), blockKey(1, 11))
  assert.notEqual(blockKey(1, 11), blockKey(11, 1))
})

test('the operator whose departure is open owns it', () => {
  assert.equal(ownsOpenDeparture('0-0', TRAINS), true)
  assert.equal(ownsOpenDeparture('2-0', BUSES), true)
})

test('and no other operator does - the bug itself', () => {
  // Opening the 04:50 train must leave the Golden Arrow card showing nothing.
  assert.equal(ownsOpenDeparture('0-0', BUSES), false)
  // And the other way round: opening a bus must not print it under Metrorail.
  assert.equal(ownsOpenDeparture('1-0', TRAINS), false)
})

test('nothing open means no card draws a breakdown', () => {
  assert.equal(ownsOpenDeparture(null, TRAINS), false)
  assert.equal(ownsOpenDeparture(null, []), false)
})

test('a departure filtered out by the leave-at time is nobody\'s', () => {
  // The card is asked against what is still to come, so a departure the rider has
  // filtered away takes its breakdown with it rather than stranding it on the page.
  assert.equal(ownsOpenDeparture('0-0', []), false)
})

test('option and departure index are not interchangeable', () => {
  // "1-0" and "0-1" are different departures on different operators, and a key that
  // confused them would put the breakdown on the wrong card while looking correct.
  assert.equal(ownsOpenDeparture('0-1', TRAINS), true)
  assert.equal(ownsOpenDeparture('0-1', BUSES), false)
  assert.equal(ownsOpenDeparture('1-0', BUSES), true)
  assert.equal(ownsOpenDeparture('1-0', TRAINS), false)
})

test('a list of stops narrows to the operator whose chip is pressed', () => {
  // The destinations list showed all 417 stops whatever chip was pressed - four hundred
  // Golden Arrow stops and every Metrorail station, under MyCiTi.
  const rows = [
    { operator_code: 'gabs', name: 'BELLVILLE' },
    { operator_code: 'myciti', name: 'Civic Centre' },
    { operator_code: 'metrorail', name: 'AKASIA PARK' },
    { operator_code: 'myciti', name: 'Adderley' },
  ]
  assert.deepEqual(onlyOperator(rows, 'myciti').map((r) => r.name),
                   ['Civic Centre', 'Adderley'])
  assert.deepEqual(onlyOperator(rows, 'metrorail').map((r) => r.name), ['AKASIA PARK'])
  // No chip means all of them: "All" is not a filter.
  assert.equal(onlyOperator(rows, null).length, 4)
})

test('a row with no operator on it counts as Golden Arrow', () => {
  // Everything loaded before operators existed is theirs, and a row that has lost its
  // code should not vanish from a list on that account.
  const rows = [{ name: 'CAPE TOWN' }, { operator_code: 'myciti', name: 'Adderley' }]
  assert.deepEqual(onlyOperator(rows, 'gabs').map((r) => r.name), ['CAPE TOWN'])
  assert.deepEqual(onlyOperator(rows, 'myciti').map((r) => r.name), ['Adderley'])
})
