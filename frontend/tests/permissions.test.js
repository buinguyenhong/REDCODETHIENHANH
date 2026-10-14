import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canCancelAlarm } from '../src/utils/permissions.js';

// Hồi quy: nút Hủy từng hiện cho MỌI báo động đang hiệu lực, trong khi máy chủ chỉ
// cho Admin hoặc chính người đã phát. Operator khác khoa bấm vào chỉ nhận 403 kèm
// câu "Lỗi hủy báo động", và không biết mình cần gọi cho ai.

const operator = { id: 7, role: 'OPERATOR' };
const otherOperator = { id: 8, role: 'OPERATOR' };
const admin = { id: 9, role: 'ADMIN' };

test('người đã phát hủy được báo động của mình', () => {
  assert.equal(canCancelAlarm(operator, { created_by_user_id: 7 }), true);
});

test('Operator khác khoa không hủy được báo động của người khác', () => {
  assert.equal(canCancelAlarm(otherOperator, { created_by_user_id: 7 }), false);
});

test('Admin hủy được mọi báo động', () => {
  assert.equal(canCancelAlarm(admin, { created_by_user_id: 7 }), true);
  assert.equal(canCancelAlarm(admin, { created_by_user_id: null }), true);
});

test('bản ghi thiếu người phát không mở nút Hủy cho tất cả', () => {
  // Hai giá trị null/undefined "bằng nhau" là cái bẫy của so sánh lỏng: nếu coi
  // chúng là trùng thì mọi báo động cũ thiếu created_by_user_id đều mở nút Hủy.
  assert.equal(canCancelAlarm(operator, { created_by_user_id: null }), false);
  assert.equal(canCancelAlarm(operator, {}), false);
  assert.equal(canCancelAlarm({ role: 'OPERATOR' }, { created_by_user_id: null }), false);
});

test('thiếu người dùng hoặc thiếu báo động thì không hủy được gì', () => {
  assert.equal(canCancelAlarm(null, { created_by_user_id: 7 }), false);
  assert.equal(canCancelAlarm(operator, null), false);
});
