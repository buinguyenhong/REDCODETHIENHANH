import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mergeAlarmQueue } from '../src/utils/alarmQueue.js';

const alarm = (id, seq = id) => ({ alarm_id: id, server_sequence: seq, expires_at: '2026-10-07T01:00:00Z' });
const now = Date.parse('2026-10-07T00:00:00Z');

test('reconnect merges missed active alarms in FIFO without duplicates', () => {
  assert.deepEqual(mergeAlarmQueue([alarm(1)], [alarm(2), alarm(1)], new Set(), now).map(a => a.alarm_id), [1, 2]);
});
test('sync removes offline cancelled/expired alarms and retains racing live arrival', () => {
  const previous = [alarm(1), { ...alarm(3), localReceivedAt: 101 }];
  assert.deepEqual(mergeAlarmQueue(previous, [alarm(2)], new Set(), now, 100).map(a => a.alarm_id), [2, 3]);
});
test('terminal tombstones prevent in-flight sync replay; dismissed is local', () => {
  assert.deepEqual(mergeAlarmQueue([], [alarm(1), alarm(2)], new Set([1]), now).map(a => a.alarm_id), [2]);
  assert.equal(mergeAlarmQueue([], [alarm(1)], new Set(), Date.parse(alarm(1).expires_at)).length, 0);
});
