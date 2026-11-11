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

/**
 * Tạo bộ theo dõi trạng thái hiển thị / âm thanh cho báo động đang ở đầu hàng đợi.
 *
 * Nếu cùng một ``alarmId`` được thử phát lại âm thanh (ví dụ sau khi người trực bấm
 * mở khóa loa), giữ nguyên ``displayedSent`` từ lượt trước để không gửi thừa DISPLAYED.
 */
export function createHeadAlarmTracker(alarmId, previousTracker = null) {
  const sameAlarm = previousTracker && previousTracker.alarmId === alarmId;
  return {
    alarmId,
    displayed: true,
    displayedSent: sameAlarm ? Boolean(previousTracker.displayedSent) : false,
    audioEvent: null,
    audioError: null,
    audioStartedSent: false,
    audioTerminalSent: false,
  };
}

export function recordHeadAudioStarted(tracker, alarmId) {
  if (!tracker || tracker.alarmId !== alarmId) return;
  tracker.audioEvent = 'AUDIO_STARTED';
  tracker.audioError = null;
}

export function recordHeadAudioCompleted(tracker, alarmId) {
  if (!tracker || tracker.alarmId !== alarmId) return;
  tracker.audioEvent = 'AUDIO_COMPLETED';
}

export function recordHeadAudioFailed(tracker, alarmId, errorMessage) {
  if (!tracker || tracker.alarmId !== alarmId) return;
  tracker.audioEvent = 'AUDIO_FAILED';
  tracker.audioError = errorMessage || 'Autoplay blocked';
  tracker.audioTerminalSent = false;
}

/**
 * Đẩy các sự kiện ``DISPLAYED`` / ``AUDIO_*`` chưa gửi của báo động đầu hàng đợi
 * qua WebSocket theo đúng thứ tự đơn điệu mà máy chủ yêu cầu.
 *
 * Giải quyết ca mất trạng thái khi trạm chuyển từ Báo động 1 sang Báo động 2 lúc
 * mạng LAN tạm đứt: khi kết nối mở lại và ``synchronize()`` đã gửi ``RECEIVED``,
 * hàm này gửi bù ``DISPLAYED`` rồi ``AUDIO_STARTED``/``AUDIO_FAILED``/``AUDIO_COMPLETED``.
 */
export function flushHeadAlarmEvents(socket, tracker, stationCode, openState = 1) {
  if (!tracker || !stationCode || !socket || socket.readyState !== openState) {
    return [];
  }
  const sent = [];
  if (tracker.displayed && !tracker.displayedSent) {
    const frame = {
      type: 'STATION_EVENT',
      event_type: 'DISPLAYED',
      alarm_id: tracker.alarmId,
    };
    socket.send(JSON.stringify(frame));
    tracker.displayedSent = true;
    sent.push(frame);
  }
  if (tracker.audioEvent === 'AUDIO_STARTED' || tracker.audioEvent === 'AUDIO_COMPLETED') {
    if (!tracker.audioStartedSent) {
      const frame = {
        type: 'STATION_EVENT',
        event_type: 'AUDIO_STARTED',
        alarm_id: tracker.alarmId,
        metadata: { station_code: stationCode },
      };
      socket.send(JSON.stringify(frame));
      tracker.audioStartedSent = true;
      sent.push(frame);
    }
    if (tracker.audioEvent === 'AUDIO_COMPLETED' && !tracker.audioTerminalSent) {
      const frame = {
        type: 'STATION_EVENT',
        event_type: 'AUDIO_COMPLETED',
        alarm_id: tracker.alarmId,
        metadata: { station_code: stationCode },
      };
      socket.send(JSON.stringify(frame));
      tracker.audioTerminalSent = true;
      sent.push(frame);
    }
  } else if (tracker.audioEvent === 'AUDIO_FAILED' && !tracker.audioTerminalSent) {
    const frame = {
      type: 'STATION_EVENT',
      event_type: 'AUDIO_FAILED',
      alarm_id: tracker.alarmId,
      metadata: {
        station_code: stationCode,
        error: tracker.audioError || 'Autoplay blocked',
      },
    };
    socket.send(JSON.stringify(frame));
    tracker.audioTerminalSent = true;
    sent.push(frame);
  }
  return sent;
}
