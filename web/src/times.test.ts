/**
 * How an approximate time reads, and the day it read backwards.
 *
 *     node --test src/times.test.ts        (or: npm test)
 *
 * Mukhethwa opened a Kraaifontein to Woodstock trip and found
 *
 *     Woodstock (your stop)  get off here   after 06:30
 *     CAPE TOWN (terminus)                       06:30
 *
 * The clock was right. The word was the opposite of true: the bus reaches Cape Town at
 * 06:30 and passes Woodstock on the way there, so the rider's point comes BEFORE it. Told
 * to expect the bus after 06:30, they would watch it go past and then wait for one that
 * had already gone.
 *
 * Nothing that checks times could catch that, because the time was not wrong. So these
 * check the words.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  longTime, shortTime, boundIsUseful, clockFace, howLong, isBound, NO_TIME,
} from './times.ts'

test('a published time is printed as it stands', () => {
  assert.deepEqual(longTime('05:10', false), { text: '05:10', approx: false })
  // A footnote letter survives: 16:45b and 16:45 are different departures.
  assert.equal(longTime('16:45b', false).text, '16:45b')
  // PRASA times weekend trains to the half minute. Nobody catches a train to the second.
  assert.equal(clockFace('05:32:30'), '05:32')
})

test('a floor reads "after", because the bus has already left that time behind', () => {
  assert.deepEqual(longTime('from 05:20', true), { text: 'after 05:20', approx: true })
})

test('a ceiling reads "before", which is the bug this file exists for', () => {
  assert.deepEqual(longTime('by 06:30', true), { text: 'before 06:30', approx: true })
  assert.notEqual(longTime('by 06:30', true).text, 'after 06:30')
})

test('an interpolation between two timed stops reads "about"', () => {
  assert.deepEqual(longTime('about 07:12', true), { text: 'about 07:12', approx: true })
})

test('a bound with no word on it is read as a floor', () => {
  // The connections queries build "from 05:20" in SQL and the planner now words every
  // bound it sends, so this is the older shape rather than a live one. It stays a floor
  // because that is what every wordless bound in this app has ever meant.
  assert.equal(longTime('05:20', true).text, 'after 05:20')
})

test('words the caller chose are left alone', () => {
  // "via" for a stop the bus merely passes; NO_TIME where even a bound said nothing.
  assert.equal(longTime('via', true).text, 'via')
  assert.equal(longTime(NO_TIME, true).text, NO_TIME)
})

test('a departure button says approximate without saying which way', () => {
  // One symbol for all three, deliberately: a tilde overstates nothing, and which way a
  // bound leans is a sentence that does not fit on a chip.
  for (const raw of ['from 05:20', 'by 05:20', 'about 05:20', '05:20']) {
    assert.equal(shortTime(raw, true).text, '~05:20', `short form of ${raw}`)
  }
  assert.deepEqual(shortTime('05:20', false), { text: '05:20', approx: false })
  assert.equal(shortTime('via', true).text, NO_TIME)
})

test('a value can be asked whether it is a bound', () => {
  // A connection leg carries no approx flag, so the value is the only thing that knows.
  // Pulling the clock out of "from 05:20" and printing 05:20 in the largest type on the
  // card is the same overstatement as "after 06:30", made by dropping the word rather
  // than choosing the wrong one.
  assert.equal(isBound('from 05:20'), true)
  assert.equal(isBound('by 06:30'), true)
  assert.equal(isBound('about 07:12'), true)
  assert.equal(isBound('05:20'), false)
  assert.equal(isBound('16:45b'), false)
  assert.equal(isBound('via'), false)
  assert.equal(isBound(null), false)
  assert.equal(isBound(undefined), false)
})

test('a bound that only repeats the boarding time is not worth showing', () => {
  // Getting off at a via stop, the floor is often the very stop you got on at, and
  // "05:20 to after 05:20" hints the ride is instant.
  assert.equal(boundIsUseful(320, true, 320), false)
  assert.equal(boundIsUseful(319, true, 320), false)
  assert.equal(boundIsUseful(321, true, 320), true)
  // A published time is always worth showing, however close to the boarding time.
  assert.equal(boundIsUseful(320, false, 320), true)
})

test('a duration reads as a duration, not as a decimal', () => {
  // "1 h 20" reads as 1.20. Three formatters disagreed about the same journey: a
  // departure said "1h 6m", a journey with a change said "1 h 20", a card header said
  // "115 min" and never reached for hours at all.
  assert.equal(howLong(80), '1h 20m')
  assert.equal(howLong(66), '1h 6m')
  assert.equal(howLong(115), '1h 55m')
  assert.equal(howLong(175), '2h 55m')
})

test('under an hour stays in minutes, and a whole hour drops them', () => {
  // "0h 40m" is worse than "40 min", and "2h 0m" is not how anybody says it.
  assert.equal(howLong(40), '40 min')
  assert.equal(howLong(59), '59 min')
  assert.equal(howLong(60), '1h')
  assert.equal(howLong(120), '2h')
  assert.equal(howLong(1), '1 min')
})

test('an approximate duration carries the same tilde as an approximate time', () => {
  assert.equal(howLong(80, true), '~1h 20m')
  assert.equal(howLong(40, true), '~40 min')
  assert.equal(howLong(60, true), '~1h')
})

test('nothing to say is null, not a zero', () => {
  // The connection views turn this into "time not published"; a bare "0 min" there would
  // read as a journey that takes no time at all.
  assert.equal(howLong(null), null)
  assert.equal(howLong(undefined), null)
  assert.equal(howLong(-5), null)
  assert.equal(howLong(0), '0 min')
})
