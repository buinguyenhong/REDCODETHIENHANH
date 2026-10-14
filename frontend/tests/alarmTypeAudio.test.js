import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeAudioSequence,
  parseAudioSequenceText,
  formatAudioSequenceText,
  addAudioPath,
  removeAudioPathAt,
} from '../src/utils/alarmTypeAudio.js';

// Hồi quy: form Admin từng có HAI ô cùng ghi vào một trường chuỗi
// ``audio_file_path`` — một textarea nhiều dòng và một <select required>. Chọn một
// tệp ở ô select ghi đè toàn bộ nội dung vừa gõ; gõ nhiều dòng thì ô select không
// khớp giá trị nào và trình duyệt chặn submit vì ``required``. Hai lối nhập cùng
// sửa một MẢNG có thứ tự thì không còn cảnh đó.

test('chọn một tệp không xóa những tệp đã khai trong ô văn bản', () => {
  const typed = parseAudioSequenceText('/assets/audio/a.wav\n/assets/audio/b.wav');
  const afterPick = addAudioPath(typed, '/assets/audio/c.wav');
  assert.deepEqual(afterPick, [
    '/assets/audio/a.wav',
    '/assets/audio/b.wav',
    '/assets/audio/c.wav',
  ]);
});

test('thứ tự phát được giữ nguyên, không sắp xếp lại', () => {
  const sequence = ['/assets/audio/z.wav', '/assets/audio/a.wav'];
  assert.deepEqual(normalizeAudioSequence(sequence), sequence);
  assert.equal(formatAudioSequenceText(sequence), '/assets/audio/z.wav\n/assets/audio/a.wav');
});

test('chọn lại đúng tệp đã có thì không thêm trùng và không đổi tham chiếu', () => {
  const sequence = ['/assets/audio/a.wav'];
  const same = addAudioPath(sequence, '/assets/audio/a.wav');
  assert.equal(same, sequence, 'trả về đúng mảng cũ để React khỏi render lại vô ích');
  assert.deepEqual(same, ['/assets/audio/a.wav']);
});

test('chọn ô trống (placeholder) không thêm gì', () => {
  const sequence = ['/assets/audio/a.wav'];
  assert.equal(addAudioPath(sequence, ''), sequence);
  assert.deepEqual(addAudioPath(null, ''), []);
});

test('xóa đúng vị trí, giữ nguyên các tệp còn lại', () => {
  const sequence = ['/assets/audio/a.wav', '/assets/audio/b.wav', '/assets/audio/c.wav'];
  assert.deepEqual(removeAudioPathAt(sequence, 1), ['/assets/audio/a.wav', '/assets/audio/c.wav']);
  assert.deepEqual(removeAudioPathAt(sequence, 0), ['/assets/audio/b.wav', '/assets/audio/c.wav']);
});

test('xóa vị trí không hợp lệ không làm mất tệp nào', () => {
  const sequence = ['/assets/audio/a.wav'];
  assert.equal(removeAudioPathAt(sequence, 5), sequence);
  assert.equal(removeAudioPathAt(sequence, -1), sequence);
});

test('dòng trắng và khoảng trắng thừa bị loại khi lưu, nhưng vẫn gõ được', () => {
  const typed = parseAudioSequenceText('/assets/audio/a.wav\n\n   \n/assets/audio/b.wav\n');
  assert.equal(typed.length, 5, 'giữ dòng trắng để gõ xuống dòng không nhảy con trỏ');
  assert.deepEqual(normalizeAudioSequence(typed), [
    '/assets/audio/a.wav',
    '/assets/audio/b.wav',
  ]);
  assert.deepEqual(normalizeAudioSequence(['  /assets/audio/a.wav  ']), ['/assets/audio/a.wav']);
});

test('chuỗi rỗng cho ra mảng rỗng để form chặn ở bước kiểm tra', () => {
  assert.deepEqual(normalizeAudioSequence(parseAudioSequenceText('')), []);
  assert.deepEqual(normalizeAudioSequence(null), []);
  assert.deepEqual(normalizeAudioSequence(['', '   ']), []);
});

test('vòng gõ -> lưu -> mở lại form cho ra đúng chuỗi ban đầu', () => {
  const original = ['/assets/audio/a.wav', '/assets/audio/b.wav'];
  const text = formatAudioSequenceText(original);
  assert.deepEqual(normalizeAudioSequence(parseAudioSequenceText(text)), original);
});
