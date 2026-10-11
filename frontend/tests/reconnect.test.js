import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reconnectDelay, MAX_RECONNECT_DELAY_MS, SESSION_CONFLICT_RETRY_MS } from '../src/utils/reconnect.js';

// Hồi quy: backoff cũ là `1000 * 1.5^attempts` không jitter, và onopen luôn đặt lại
// bộ đếm. Hệ quả là sau khi máy chủ khởi động lại, 50–100 trạm hẹn lại đúng cùng
// một mốc (+1000ms) rồi kết nối đồng loạt, mỗi lượt kèm một lượt ghi DB + broadcast.

test('jitter spreads clients that would otherwise retry on the same tick', () => {
  const attempts = 3;
  const base = Math.min(1000 * Math.pow(1.5, attempts), MAX_RECONNECT_DELAY_MS);
  const low = reconnectDelay(attempts, () => 0);
  const high = reconnectDelay(attempts, () => 1);
  assert.ok(Math.abs(low - base * 0.7) <= 1, `sàn jitter phải quanh ${base * 0.7}, nhận ${low}`);
  assert.ok(Math.abs(high - base * 1.3) <= 1, `trần jitter phải quanh ${base * 1.3}, nhận ${high}`);
  assert.ok(high - low > 1000, 'khoảng jitter phải đủ rộng để tách các trạm ra');
});

test('delay never exceeds the configured ceiling by more than the jitter band', () => {
  for (let attempts = 0; attempts < 20; attempts++) {
    assert.ok(reconnectDelay(attempts, () => 1) <= Math.round(MAX_RECONNECT_DELAY_MS * 1.3));
    assert.ok(reconnectDelay(attempts, () => 0) >= Math.round(Math.min(1000 * Math.pow(1.5, attempts), MAX_RECONNECT_DELAY_MS) * 0.7));
  }
});

test('delay grows with attempts until it reaches the ceiling', () => {
  const first = reconnectDelay(0, () => 0.5);
  const later = reconnectDelay(3, () => 0.5);
  assert.ok(later > first);
  // Khi đã chạm trần, backoff cơ sở không tăng nữa.
  assert.equal(reconnectDelay(10, () => 0.5), reconnectDelay(30, () => 0.5));
});

test('session conflict floor prevents the one-second ping-pong between two devices', () => {
  // onopen đặt lại attempts = 0 nên nếu không có sàn, mọi vòng 4001 đều chờ ~1s.
  for (let i = 0; i < 5; i++) {
    assert.ok(reconnectDelay(0, () => 0, SESSION_CONFLICT_RETRY_MS) === SESSION_CONFLICT_RETRY_MS);
    assert.ok(reconnectDelay(0, () => 1, SESSION_CONFLICT_RETRY_MS) >= SESSION_CONFLICT_RETRY_MS);
  }
  assert.ok(reconnectDelay(0, () => 0) < SESSION_CONFLICT_RETRY_MS, 'không có sàn thì backoff thường vẫn ngắn');
});
