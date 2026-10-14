/**
 * Ai được làm gì với một báo động.
 *
 * Cùng một luật phải đúng ở hai nơi: máy chủ từ chối bằng 403, còn giao diện phải
 * giấu nút đi. Nếu giao diện hiện nút mà máy chủ từ chối thì người trực chỉ nhận
 * một câu "Lỗi hủy báo động" và không biết mình cần gọi cho ai.
 */

/**
 * Có được hủy báo động này không — khớp với POST /api/alarms/{id}/cancel.
 *
 * Admin hủy được mọi báo động; người dùng thường chỉ hủy được báo động do chính
 * mình phát.
 */
export function canCancelAlarm(user, alarm) {
  if (!user || !alarm) return false;
  if (user.role === 'ADMIN') return true;
  // So sánh chặt: thiếu id ở một trong hai phía KHÔNG được coi là trùng nhau, nếu
  // không thì một bản ghi thiếu ``created_by_user_id`` sẽ mở nút Hủy cho tất cả.
  if (user.id == null || alarm.created_by_user_id == null) return false;
  return alarm.created_by_user_id === user.id;
}
