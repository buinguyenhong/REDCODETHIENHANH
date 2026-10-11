// Chính sách thử lại kết nối WebSocket của trạm nhận.
//
// Tách khỏi React context để đo được bằng test: đây là những con số quyết định
// hành vi của 50–100 thiết bị cùng lúc sau khi máy chủ khởi động lại.

/** Trần backoff thông thường, tính bằng ms. */
export const MAX_RECONNECT_DELAY_MS = 10000;

/** Chờ tối thiểu khi trạm bị một phiên khác chiếm chỗ (đóng 4001). */
export const SESSION_CONFLICT_RETRY_MS = 15000;

/**
 * Tính thời gian chờ trước lần thử kết nối lại kế tiếp.
 *
 * Backoff cơ sở tăng 1.5 lần mỗi lần thất bại, chặn trần ở MAX_RECONNECT_DELAY_MS.
 * Nhân thêm jitter trong khoảng 0.7–1.3 để các trạm không hẹn lại đúng cùng một
 * mốc: sau khi máy chủ khởi động lại, tất cả nhận onclose trong cùng một giây và
 * nếu không jitter thì chúng đập vào máy chủ đồng loạt, mỗi lượt kèm một lượt ghi
 * DB + broadcast, dồn hết lên một worker duy nhất.
 *
 * @param {number} attempts Số lần đã thử lại (0 cho lần chờ đầu tiên).
 * @param {() => number} random Nguồn ngẫu nhiên, thay được khi test.
 * @param {number} minDelayMs Sàn thời gian chờ, dùng cho ca tranh phiên (4001).
 */
export function reconnectDelay(attempts, random = Math.random, minDelayMs = 0) {
  const base = Math.min(1000 * Math.pow(1.5, attempts), MAX_RECONNECT_DELAY_MS);
  const jittered = Math.round(base * (0.7 + random() * 0.6));
  return Math.max(minDelayMs, jittered);
}
