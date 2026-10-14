/**
 * Các phép xử lý chuỗi âm thanh của một mã báo động.
 *
 * Chuỗi âm thanh là MẢNG có thứ tự (``audio_sequence``) — thứ tự phát là thông tin
 * thật, không phải chi tiết trình bày. Giao diện Admin có hai lối nhập cùng sửa một
 * mảng: ô văn bản nhiều dòng để dán sẵn danh sách, và ô chọn tệp để thêm từng tệp
 * đã tải lên. Trước đây hai lối đó ghi vào hai trường khác nhau của cùng một chuỗi
 * nối bằng xuống dòng, nên chọn một tệp là xóa sạch nội dung vừa gõ. Gom phép xử lý
 * vào đây để cả hai lối cùng sửa một sự thật, và để kiểm thử được.
 */

/** Chuỗi âm thanh đã chuẩn hóa để gửi lên API: bỏ dòng trắng, cắt khoảng trắng. */
export function normalizeAudioSequence(sequence) {
  return (sequence || []).map((path) => String(path).trim()).filter(Boolean);
}

/**
 * Nội dung ô văn bản -> mảng.
 *
 * Giữ lại cả dòng trắng để gõ xuống dòng vẫn round-trip được với ``join('\n')``;
 * việc lọc dòng trắng chỉ xảy ra lúc lưu.
 */
export function parseAudioSequenceText(text) {
  return String(text ?? '').split('\n');
}

/** Nối mảng thành nội dung ô văn bản. */
export function formatAudioSequenceText(sequence) {
  return (sequence || []).join('\n');
}

/**
 * Thêm một tệp vào cuối chuỗi.
 *
 * Thêm trùng thì giữ nguyên mảng cũ (trả về đúng tham chiếu cũ để React khỏi render
 * lại). Phát cùng một tệp hai lần liền là chủ ý hợp lệ về mặt âm thanh, nhưng nó
 * không phải thứ ô chọn tệp diễn đạt được — muốn vậy thì sửa ở ô văn bản.
 */
export function addAudioPath(sequence, path) {
  if (!path) return sequence || [];
  const current = sequence || [];
  if (current.includes(path)) return current;
  return [...current, path];
}

/** Bỏ tệp ở vị trí ``index``. Vị trí không hợp lệ thì trả về mảng cũ. */
export function removeAudioPathAt(sequence, index) {
  const current = sequence || [];
  if (index < 0 || index >= current.length) return current;
  return current.filter((_, i) => i !== index);
}
