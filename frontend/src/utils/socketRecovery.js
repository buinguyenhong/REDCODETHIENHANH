/**
 * Gỡ một socket đã mất nhịp tim và hẹn kết nối lại NGAY, không chờ sự kiện close.
 *
 * Vì sao không thể chỉ gọi ``ws.close()`` rồi để ``onclose`` lo phần còn lại:
 * ``close()`` chỉ bắt đầu quá trình đóng. Khi socket đã nửa mở — máy chủ biến mất
 * mà không gửi FIN/RST, đúng kiểu mất mạng LAN hoặc máy chủ bị tắt nguồn — trình
 * duyệt giữ nó ở trạng thái CLOSING cho tới khi hết hạn chờ của TCP, và ``onclose``
 * chỉ bắn sau đó. Suốt 30–60 giây ấy màn hình trạm vẫn hiện "đã kết nối" trong khi
 * không có nhịp tim nào qua lại, và tệ hơn: không có vòng kết nối lại nào được hẹn,
 * nên khi báo động phát ra thì còi không hú ở trạm đó.
 *
 * Hàm này làm phần việc mà ``onclose`` lẽ ra phải làm, rồi tự hẹn kết nối lại. Nó
 * gỡ hết handler trước khi đóng để ``onclose`` đến muộn kia trở thành vô hại —
 * nếu không, một lượt đóng sẽ sinh HAI lượt kết nối lại, và hai socket cùng sống
 * trên một trạm thì máy chủ đá nhau bằng mã 4001.
 *
 * @param {object}   options
 * @param {object}   options.socket             socket đã hết nhịp tim
 * @param {Function} options.clearHeartbeat     dừng vòng gửi nhịp tim
 * @param {Function} options.markDisconnected   đặt trạng thái UI về "mất kết nối"
 * @param {Function} options.forgetSocket       bỏ tham chiếu tới socket này
 * @param {Function} options.reconnect          hẹn một lượt kết nối lại
 */
export function recoverFromHeartbeatTimeout({
  socket,
  clearHeartbeat,
  markDisconnected,
  forgetSocket,
  reconnect,
}) {
  clearHeartbeat();
  markDisconnected();
  forgetSocket();

  // Gỡ handler TRƯỚC khi đóng: đây là điểm chặn lượt kết nối lại thứ hai.
  socket.onclose = null;
  socket.onmessage = null;
  socket.onerror = null;
  try {
    socket.close();
  } catch (_) {
    // Socket đã chết theo cách khác; việc cần làm là kết nối lại, không phải báo lỗi.
  }

  reconnect();
}
