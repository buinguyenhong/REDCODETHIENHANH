export function mergeAlarmQueue(previous, incoming, dismissed, now, syncStartedAt = null) {
  const ids = new Set(incoming.map(alarm => alarm.alarm_id));
  const retained = syncStartedAt === null ? previous : previous.filter(alarm => ids.has(alarm.alarm_id) || alarm.localReceivedAt >= syncStartedAt);
  return [...new Map([...retained, ...incoming].filter(alarm =>
    !dismissed.has(alarm.alarm_id) && (!alarm.expires_at || Date.parse(alarm.expires_at) > now)
  ).map(alarm => [alarm.alarm_id, alarm])).values()].sort((a, b) => a.server_sequence - b.server_sequence);
}

/**
 * Chọn ra những báo động được phép ACK RECEIVED sau một lần đồng bộ.
 *
 * Chỉ báo động THẬT SỰ vào hàng đợi hiển thị mới được xác nhận. Gửi RECEIVED theo
 * mảng thô từ máy chủ sẽ khai "đã nhận" cho cả báo động đã hết hạn hoặc trạm đã
 * tắt tại chỗ: máy chủ chuyển PENDING → DELIVERED và ghi received_at, nên nhật ký
 * ghi nhận trạm đã nhận một báo động mà không ai nghe thấy.
 */
export function alarmsToAcknowledge(serverAlarms, mergedQueue) {
  const queued = new Set(mergedQueue.map(alarm => alarm.alarm_id));
  return serverAlarms.filter(alarm => queued.has(alarm.alarm_id)).map(alarm => alarm.alarm_id);
}
