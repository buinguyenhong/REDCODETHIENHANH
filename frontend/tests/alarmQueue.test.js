import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mergeAlarmQueue, alarmsToAcknowledge } from '../src/utils/alarmQueue.js';

const alarm = (id, seq = id, extra = {}) => ({ alarm_id: id, server_sequence: seq, expires_at: '2026-10-07T01:00:00Z', ...extra });
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

// --- Hồi quy: ACK RECEIVED sau đồng bộ ---
// Trước đây synchronize() gửi RECEIVED cho MỌI báo động trong mảng thô từ máy chủ.
// Báo động đã hết hạn hoặc trạm đã tắt tại chỗ vì thế vẫn được khai "đã nhận":
// máy chủ chuyển PENDING → DELIVERED và ghi received_at, nhật ký ghi nhận trạm đã
// nhận một báo động mà không ai nghe thấy.

test('sync only acknowledges alarms that actually entered the display queue', () => {
  const serverAlarms = [alarm(1), alarm(2, 2, { expires_at: '2026-10-07T00:10:00Z' }), alarm(3)];
  // 2 đã hết hạn, 3 đã bị tắt tại chỗ ở thiết bị này.
  const merged = mergeAlarmQueue([], serverAlarms, new Set([3]), Date.parse('2026-10-07T00:30:00Z'));
  assert.deepEqual(merged.map(a => a.alarm_id), [1]);
  assert.deepEqual(alarmsToAcknowledge(serverAlarms, merged), [1]);
});

test('expired alarm is never acknowledged even though the server still returns it', () => {
  const expired = alarm(7, 7, { expires_at: '2026-10-06T23:00:00Z' });
  const merged = mergeAlarmQueue([], [expired], new Set(), now);
  assert.deepEqual(merged, []);
  assert.deepEqual(alarmsToAcknowledge([expired], merged), []);
});

test('locally dismissed alarm is not acknowledged on the next sync', () => {
  const dismissed = new Set([5]);
  const serverAlarms = [alarm(4), alarm(5)];
  const merged = mergeAlarmQueue([], serverAlarms, dismissed, now);
  assert.deepEqual(alarmsToAcknowledge(serverAlarms, merged), [4]);
});
