import { test } from 'node:test';
import assert from 'node:assert/strict';
import { recoverFromHeartbeatTimeout } from '../src/utils/socketRecovery.js';

// Hồi quy: khi hết nhịp tim, client chỉ gọi ``ws.close()`` rồi chờ ``onclose``. Với
// socket nửa mở (máy chủ biến mất không gửi FIN/RST) trình duyệt giữ nó ở CLOSING
// hàng chục giây, và suốt thời gian đó KHÔNG có lượt kết nối lại nào được hẹn —
// màn hình trạm vẫn hiện "đã kết nối" nhưng còi không hú.

function makeHarness() {
  const calls = [];
  const socket = {
    closed: false,
    onclose: () => {},
    onmessage: () => {},
    onerror: () => {},
    close() { this.closed = true; calls.push('close'); },
  };
  return {
    calls,
    socket,
    clearHeartbeat: () => calls.push('clearHeartbeat'),
    markDisconnected: () => calls.push('markDisconnected'),
    forgetSocket: () => calls.push('forgetSocket'),
    reconnect: () => calls.push('reconnect'),
  };
}

test('hết nhịp tim thì hẹn kết nối lại ngay, không chờ sự kiện close', () => {
  const h = makeHarness();
  recoverFromHeartbeatTimeout({ ...h, socket: h.socket });
  assert.ok(h.calls.includes('reconnect'), 'phải hẹn kết nối lại ngay trong lượt này');
  assert.deepEqual(h.calls, [
    'clearHeartbeat',
    'markDisconnected',
    'forgetSocket',
    'close',
    'reconnect',
  ]);
  assert.equal(h.socket.closed, true, 'socket cũ vẫn phải được đóng');
});

test('onclose đến muộn không sinh thêm một lượt kết nối lại thứ hai', () => {
  const h = makeHarness();
  let lateOnclose = null;
  h.socket.onclose = () => { lateOnclose = 'called'; };
  recoverFromHeartbeatTimeout({ ...h, socket: h.socket });

  assert.equal(h.socket.onclose, null, 'handler phải bị gỡ trước khi đóng');
  assert.equal(lateOnclose, null, 'onclose đến muộn không được chạy');
  assert.equal(h.calls.filter((c) => c === 'reconnect').length, 1,
    'hai lượt kết nối lại song song sẽ bị máy chủ đá nhau bằng mã 4001');
});

test('handler cũ bị gỡ nên socket chết không còn bơm sự kiện vào state', () => {
  const h = makeHarness();
  recoverFromHeartbeatTimeout({ ...h, socket: h.socket });
  assert.equal(h.socket.onmessage, null);
  assert.equal(h.socket.onerror, null);
});

test('socket đã chết theo cách khác thì vẫn phải hẹn kết nối lại', () => {
  const h = makeHarness();
  h.socket.close = () => { throw new Error('InvalidStateError'); };
  recoverFromHeartbeatTimeout({ ...h, socket: h.socket });
  assert.equal(h.calls[h.calls.length - 1], 'reconnect',
    'close() ném lỗi không được chặn việc kết nối lại — đó mới là việc cần làm');
});
