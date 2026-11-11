import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatHospitalDate } from '../src/utils/hospitalTime.js';

test('formatHospitalDate uses Asia/Ho_Chi_Minh date during night shift (00:00-06:59 VN)', () => {
  // 2026-10-06T20:30:00Z là 03:30 sáng ngày 2026-10-07 giờ Việt Nam (UTC+7).
  // toISOString().split('T')[0] sẽ trả về '2026-10-06' (lùi mất 1 ngày).
  const nightShiftMoment = new Date('2026-10-06T20:30:00Z');
  assert.equal(formatHospitalDate(nightShiftMoment), '2026-10-07');
});

test('formatHospitalDate preserves same calendar day during afternoon in Vietnam', () => {
  const afternoonMoment = new Date('2026-10-07T08:00:00Z'); // 15:00 giờ VN
  assert.equal(formatHospitalDate(afternoonMoment), '2026-10-07');
});

