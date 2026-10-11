import { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { soundPlayer } from '../utils/soundPlayer';
import { api } from '../api/client';
import { useAuth } from './AuthContext';
import { mergeAlarmQueue, alarmsToAcknowledge } from '../utils/alarmQueue';
import { reconnectDelay, SESSION_CONFLICT_RETRY_MS } from '../utils/reconnect';
import { randomId } from '../utils/uuid';

const WebSocketContext = createContext(null);

// Ngưỡng mất nhịp tim phía client, tính bằng ms. Phải khớp với
// STATION_OFFLINE_THRESHOLD_SECONDS (15) mà máy chủ dùng để cắt kết nối: client
// gửi nhịp 5 giây một lần nên 15 giây = 3 nhịp liên tiếp không có phản hồi.
// Giá trị cũ 20000 lệch với con số 15 giây mà chính giao diện trạm ghi ra.
const HEARTBEAT_ACK_TIMEOUT_MS = 15000;

// Chờ tối thiểu khi trạm bị phiên khác chiếm chỗ (đóng 4001). Thử lại theo backoff
// thường sẽ đá nhau mỗi ~1 giây vô hạn vì onopen luôn đặt lại bộ đếm.
// (Giá trị nằm trong utils/reconnect.js để test được.)

export function WebSocketProvider({ children }) {
  const { token } = useAuth();
  const [isConnected, setIsConnected] = useState(false);
  const [activeAlarms, setActiveAlarms] = useState([]); // FIFO queue of active alarms
  const [audioReady, setAudioReady] = useState(false);
  const [audioError, setAudioError] = useState(null);
  const [displayTest, setDisplayTest] = useState(null);
  const connectionTestsRef = useRef(new Map());
  const serverOffsetRef = useRef(0);
  const [lastAck, setLastAck] = useState(null);
  const [recentStatusEvents, setRecentStatusEvents] = useState([]);
  // Server từ chối credential (đóng 1008): thử lại vô ích cho tới khi thiết bị
  // được xác nhận lại, nên trạm phải báo rõ thay vì retry im lặng.
  const [activationError, setActivationError] = useState(null);
  const activationBlockedRef = useRef(false);
  // Trạm bị một phiên khác chiếm chỗ (đóng 4001). Khác với activationError: đây
  // không phải lỗi credential nên vẫn tự thử lại, chỉ chậm hơn nhiều.
  const [sessionConflict, setSessionConflict] = useState(null);

  // Station info from localStorage if configured
  const [stationConfig, setStationConfig] = useState(() => {
    const saved = localStorage.getItem('redcode_station_config');
    return saved ? JSON.parse(saved) : null;
  });

  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const heartbeatIntervalRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const disposedRef = useRef(false);
  const lastHeartbeatAckRef = useRef(Date.now());
  const [audioRetry, setAudioRetry] = useState(0);
  const syncRetryRef = useRef(null);
  const dismissedRef = useRef(new Set(JSON.parse(localStorage.getItem('redcode_pending_dismiss') || '[]').map(item => item.alarm_id)));
  // Bản sao hàng đợi để synchronize() tính được đúng tập báo động đã vào hiển thị
  // mà không phải chạy side-effect bên trong hàm cập nhật state.
  const activeAlarmsRef = useRef([]);
  useEffect(() => { activeAlarmsRef.current = activeAlarms; }, [activeAlarms]);
  const ordered = (alarms) => mergeAlarmQueue([], alarms, dismissedRef.current, Date.now() + serverOffsetRef.current);

  const saveStationConfig = (config) => {
    soundPlayer.stop();
    dismissedRef.current = new Set();
    localStorage.removeItem('redcode_pending_dismiss');
    setAudioError(null);
    setActiveAlarms([]);
    activationBlockedRef.current = false;
    setActivationError(null);
    setSessionConflict(null);
    setStationConfig(config);
    if (config) {
      localStorage.setItem('redcode_station_config', JSON.stringify(config));
    } else {
      localStorage.removeItem('redcode_station_config');
    }
  };

  const synchronize = async () => {
    if (!stationConfig?.device_token) return;
    if (activationBlockedRef.current) return; // credential đã bị thu hồi: đồng bộ sẽ luôn 401
    const socket = wsRef.current;
    const startedAt = Date.now();
    const pending = JSON.parse(localStorage.getItem('redcode_pending_dismiss') || '[]');
    const remaining = [];
    for (const item of pending) {
      try { await api.dismissStationAlarm(item); } catch (_) { remaining.push(item); }
    }
    localStorage.setItem('redcode_pending_dismiss', JSON.stringify(remaining));
    let alarms;
    try {
      alarms = await api.getStationActiveAlarms(stationConfig.station_code, stationConfig.device_token);
    } catch (error) {
      if (!disposedRef.current && wsRef.current === socket) {
        clearTimeout(syncRetryRef.current);
        syncRetryRef.current = setTimeout(() => synchronize().catch(() => {}), 2000);
      }
      throw error;
    }
    if (alarms[0]?.server_time) serverOffsetRef.current = Date.parse(alarms[0].server_time) - Date.now();
    if (disposedRef.current || wsRef.current !== socket) return;
    const merged = mergeAlarmQueue(activeAlarmsRef.current, alarms, dismissedRef.current, Date.now() + serverOffsetRef.current, startedAt);
    setActiveAlarms(merged);

    // Chỉ ACK những báo động THẬT SỰ vào hàng đợi hiển thị (xem alarmsToAcknowledge).
    for (const alarmId of alarmsToAcknowledge(alarms, merged)) {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'STATION_EVENT', event_type: 'RECEIVED', alarm_id: alarmId }));
      }
    }
  };

  const connect = useCallback(() => {
    if (disposedRef.current || (!stationConfig?.device_token && !token)) return;
    if (activationBlockedRef.current) return; // chờ xác nhận lại thiết bị / đăng nhập lại
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    let url = `${protocol}//${host}/ws`;

    if (stationConfig && stationConfig.station_code && stationConfig.device_token) {
      url += `?type=station&station_code=${encodeURIComponent(stationConfig.station_code)}&token=${encodeURIComponent(stationConfig.device_token)}`;
    } else {
      const token = localStorage.getItem('redcode_token');
      url += `?type=dashboard${token ? `&token=${encodeURIComponent(token)}` : ''}`;
    }

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposedRef.current || wsRef.current !== ws) { ws.close(); return; }
        lastHeartbeatAckRef.current = Date.now();
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        setActivationError(null);
        setSessionConflict(null);
        console.log('[WebSocket] Kết nối thành công tới máy chủ Redcode');

        // Sync missed/active alarms for this station on connect/reconnect
        if (stationConfig && stationConfig.station_code) {
          synchronize().catch((err) => console.warn('Lỗi đồng bộ:', err));
        }

        // Start heartbeat every 5 seconds
        if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            if (Date.now() - lastHeartbeatAckRef.current > HEARTBEAT_ACK_TIMEOUT_MS) { ws.close(); return; }
            ws.send(JSON.stringify({
              type: stationConfig?.device_token ? 'HEARTBEAT' : 'PING',
              audio_ready: soundPlayer.isAudioReady,
              client_ready: true,
            }));
          }
        }, 5000);
      };

      ws.onmessage = (event) => {
        if (wsRef.current !== ws || disposedRef.current) return;
        try {
          const msg = JSON.parse(event.data);
          handleIncomingMessage(msg);
        } catch (e) {
          console.error('[WebSocket] Lỗi xử lý tin nhắn:', e);
        }
      };

      ws.onclose = (event) => {
        if (disposedRef.current || wsRef.current !== ws) return;
        setIsConnected(false);
        if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);

        // 1008 = server từ chối credential (thiết bị chưa xác nhận, token đã bị
        // thu hồi, hoặc phiên đăng nhập hết hạn). Thử lại không thể thành công
        // nên dừng vòng retry và báo rõ, thay vì để trạm hiện OFFLINE im lặng
        // giống như mất mạng.
        if (event.code === 1008) {
          wsRef.current = null;
          reconnectAttemptsRef.current = 0;
          activationBlockedRef.current = true;
          const isStation = !!stationConfig?.device_token;
          setActivationError({
            scope: isStation ? 'station' : 'dashboard',
            reason: event.reason || '',
            message: isStation
              ? 'Thiết bị này chưa được xác nhận cho trạm, hoặc credential của trạm đã bị thu hồi.'
              : 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
          });
          console.warn('[WebSocket] Credential bị từ chối (1008):', event.reason || '(không có lý do)');
          return;
        }

        // 4001 = trạm này vừa bị một phiên khác chiếm chỗ (mở cùng station_code ở
        // tab hoặc máy khác). Không phải lỗi credential nên vẫn thử lại, nhưng
        // phải chờ lâu: onopen luôn đặt lại bộ đếm nên backoff thường sẽ cho ra
        // đúng 1 giây mỗi vòng — hai máy đá nhau vô hạn, mỗi vòng kèm một lượt ghi
        // DB và broadcast STATION_STATUS.
        if (event.code === 4001) {
          setSessionConflict({
            message: 'Trạm này đang được mở ở một thiết bị hoặc tab khác. Thiết bị này sẽ tự thử lại sau 15 giây; hãy đóng phiên còn lại nếu đây mới là máy trực.',
          });
          console.warn('[WebSocket] Phiên trạm bị chiếm chỗ (4001):', event.reason || '(không có lý do)');
          scheduleReconnect(SESSION_CONFLICT_RETRY_MS);
          return;
        }

        scheduleReconnect();
      };

      ws.onerror = (err) => {
        console.warn('[WebSocket] Lỗi kết nối:', err);
        ws.close();
      };
    } catch (err) {
      console.error('[WebSocket] Lỗi khởi tạo socket:', err);
      scheduleReconnect();
    }
  }, [stationConfig, token]);

  const scheduleReconnect = (minDelayMs = 0) => {
    if (disposedRef.current) return;
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    // Jitter nằm trong reconnectDelay(): sau khi máy chủ khởi động lại, toàn bộ
    // 50–100 trạm nhận onclose cùng một giây; không jitter thì chúng dập vào máy
    // chủ đồng loạt.
    const delay = reconnectDelay(reconnectAttemptsRef.current, Math.random, minDelayMs);
    reconnectAttemptsRef.current++;
    reconnectTimeoutRef.current = setTimeout(() => {
      console.log(`[WebSocket] Thử kết nối lại (lần ${reconnectAttemptsRef.current})...`);
      connect();
    }, delay);
  };

  const handleIncomingMessage = (msg) => {
    const serverTime = msg.server_time || msg.timestamp || msg.data?.server_time;
    if (serverTime) serverOffsetRef.current = Date.parse(serverTime) - Date.now();
    switch (msg.type) {
      case 'PONG': {
        lastHeartbeatAckRef.current = Date.now();
        const pending = connectionTestsRef.current.get(msg.request_id);
        if (pending) { clearTimeout(pending.timer); pending.resolve(Date.now() - pending.started); connectionTestsRef.current.delete(msg.request_id); }
        break;
      }
      case 'ALARM_EVENT':
        if (!stationConfig?.station_code) break;
        if (msg.event === 'ALARM_TRIGGERED' && msg.data) {
          const alarm = msg.data;
          alarm.localReceivedAt = Date.now();
          setActiveAlarms((prev) => {
            // Avoid duplicate alarm in queue
            if (prev.some((a) => a.alarm_id === alarm.alarm_id)) return prev;
            return ordered([...prev, alarm]);
          });

          // Send RECEIVED audit event back to server
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && stationConfig?.station_code) {
            wsRef.current.send(JSON.stringify({
              type: 'STATION_EVENT',
              event_type: 'RECEIVED',
              alarm_id: alarm.alarm_id,
              metadata: { station_code: stationConfig.station_code }
            }));
          }
        }
        break;

      case 'ALARM_CANCELLED':
      case 'ALARM_EXPIRED':
        setRecentStatusEvents(prev => [msg, ...prev.slice(0, 20)]);
        if (msg.alarm_id) {
          dismissedRef.current.add(msg.alarm_id);
          setActiveAlarms((prev) => prev.filter((a) => a.alarm_id !== msg.alarm_id));
        }
        break;

      case 'AUDIO_TEST':
        console.log('[WebSocket] Nhận lệnh kiểm tra âm thanh từ Admin');
        // Dùng verifyPlayback (đường ống <audio> thật) chứ không dùng tiếng bíp
        // WebAudio: lệnh này để trả lời câu hỏi "trạm này có hú được không", nên
        // phải thử đúng thứ mà báo động thật dùng.
        soundPlayer.verifyPlayback().then(() => setAudioReady(true)).catch(() => setAudioReady(false));
        break;
      case 'SYNC_REQUIRED':
        synchronize().catch((err) => console.warn('Lỗi đồng bộ:', err));
        break;
      case 'HEARTBEAT_ACK':
        lastHeartbeatAckRef.current = Date.now();
        break;

      case 'STATION_STATUS':
        setRecentStatusEvents((prev) => [msg, ...prev.slice(0, 20)]);
        break;

      case 'ALARM_ACKNOWLEDGED':
        setLastAck(msg);
        break;

      default:
        if (msg.status === 'CANCELLED' && msg.alarm_id) {
          setActiveAlarms((prev) => prev.filter((a) => a.alarm_id !== msg.alarm_id));
        }
        break;
    }
  };

  // Play audio for current head of FIFO queue
  useEffect(() => {
    const interval = setInterval(() => setActiveAlarms(previous => {
      const valid = ordered(previous);
      return valid.length === previous.length ? previous : valid;
    }), 500);
    return () => clearInterval(interval);
  }, []);
  useEffect(() => {
    if (activeAlarms.length > 0) {
      const currentAlarm = activeAlarms[0];
      setAudioError(null);
      if (wsRef.current?.readyState === WebSocket.OPEN && stationConfig?.station_code) wsRef.current.send(JSON.stringify({ type: 'STATION_EVENT', event_type: 'DISPLAYED', alarm_id: currentAlarm.alarm_id }));
      if (currentAlarm.audio_sequence && currentAlarm.audio_sequence.length > 0) {
        soundPlayer.playAlarmSequence(
          currentAlarm.audio_sequence,
          currentAlarm.repeat_count || 4,
          currentAlarm.repeat_interval_ms || 1200,
          () => {
            // onStart: Send AUDIO_STARTED audit event
            setAudioReady(true);
            setAudioError(null);
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && stationConfig?.station_code) {
              wsRef.current.send(JSON.stringify({
                type: 'STATION_EVENT',
                event_type: 'AUDIO_STARTED',
                alarm_id: currentAlarm.alarm_id,
                metadata: { station_code: stationConfig.station_code }
              }));
            }
          },
          () => {
            // onComplete: Send AUDIO_COMPLETED audit event
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && stationConfig?.station_code) {
              wsRef.current.send(JSON.stringify({
                type: 'STATION_EVENT',
                event_type: 'AUDIO_COMPLETED',
                alarm_id: currentAlarm.alarm_id,
                metadata: { station_code: stationConfig.station_code }
              }));
            }
          },
          (err) => {
            // onError: Send AUDIO_FAILED audit event and update UI readiness
            setAudioReady(false);
            setAudioError(err?.message || 'Không phát được âm thanh');
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && stationConfig?.station_code) {
              wsRef.current.send(JSON.stringify({
                type: 'STATION_EVENT',
                event_type: 'AUDIO_FAILED',
                alarm_id: currentAlarm.alarm_id,
                metadata: { station_code: stationConfig.station_code, error: err?.message || 'Autoplay blocked' }
              }));
            }
          }
        );
      } else {
        // Báo động không có tệp âm thanh: vẫn hiện trên màn hình nhưng không hú ở
        // đâu cả. Im lặng bỏ qua là kiểu hỏng tệ nhất — trạm trông như đã nhận báo
        // động mà không ai nghe thấy gì, và nhật ký không ghi lại điều gì bất thường.
        setAudioReady(false);
        setAudioError('Báo động này không có tệp âm thanh để phát — trạm không thể hú');
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && stationConfig?.station_code) {
          wsRef.current.send(JSON.stringify({
            type: 'STATION_EVENT',
            event_type: 'AUDIO_FAILED',
            alarm_id: currentAlarm.alarm_id,
            metadata: { station_code: stationConfig.station_code, error: 'Báo động không có tệp âm thanh' }
          }));
        }
      }
    } else {
      soundPlayer.stop();
    }
    return () => soundPlayer.stop();
  }, [activeAlarms[0]?.alarm_id, stationConfig, audioRetry]);

  // Local Dismiss of current alarm
  const dismissCurrentAlarm = async (note = '') => {
    if (activeAlarms.length === 0) return;
    const currentAlarm = activeAlarms[0];

    soundPlayer.stop();
    dismissedRef.current.add(currentAlarm.alarm_id);

    // Remove from local queue immediately
    setActiveAlarms((prev) => prev.slice(1));

    // Send local dismissal to backend
    if (stationConfig && stationConfig.station_code) {
      const action = { alarm_id: currentAlarm.alarm_id, station_code: stationConfig.station_code, device_token: stationConfig.device_token, note };
      const pending = JSON.parse(localStorage.getItem('redcode_pending_dismiss') || '[]');
      localStorage.setItem('redcode_pending_dismiss', JSON.stringify([...pending, action]));
      try {
        await api.dismissStationAlarm(action);
        const latest = JSON.parse(localStorage.getItem('redcode_pending_dismiss') || '[]');
        localStorage.setItem('redcode_pending_dismiss', JSON.stringify(latest.filter(item => item.alarm_id !== action.alarm_id)));
      } catch (err) {
        console.warn('Gửi xác nhận tắt báo động lỗi:', err);
      }
    }
  };

  const unlockAudio = async () => {
    if (activeAlarms.length && soundPlayer.isPlaying) return false;
    const success = await soundPlayer.unlockAudio();
    setAudioReady(success);
    if (success) setAudioRetry(value => value + 1);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'AUDIO_STATE_CHANGED',
        audio_ready: success,
      }));
    }
    return success;
  };

  useEffect(() => {
    disposedRef.current = false;
    wsRef.current = null;
    setIsConnected(false);
    connect();
    return () => {
      disposedRef.current = true;
      if (wsRef.current) wsRef.current.onclose = null;
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
      clearTimeout(syncRetryRef.current);
    };
  }, [connect]);

  const testConnection = () => new Promise((resolve, reject) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      reject(new Error(activationError?.message || 'Trạm chưa kết nối WebSocket'));
      return;
    }
    const request_id = randomId();
    const timer = setTimeout(() => { connectionTestsRef.current.delete(request_id); reject(new Error('Không nhận phản hồi trong 5 giây')); }, 5000);
    connectionTestsRef.current.set(request_id, { resolve, reject, timer, started: Date.now() });
    wsRef.current.send(JSON.stringify({ type: 'PING', request_id }));
  });

  // Cho phép thử lại thủ công sau khi đã xác nhận lại thiết bị / đăng nhập lại.
  const retryConnection = () => {
    activationBlockedRef.current = false;
    setActivationError(null);
    setSessionConflict(null);
    reconnectAttemptsRef.current = 0;
    connect();
  };
  const testDisplay = () => setDisplayTest({ alarm_id: 'display-test', code: 'KIỂM TRA HIỂN THỊ', name: 'ĐÂY LÀ CẢNH BÁO THỬ', department: stationConfig?.department, location: stationConfig?.location, note: 'Không tạo alarm thật, không gửi thông báo.', display_color: '#b91c1c', created_at: new Date().toISOString(), isTest: true });

  return (
    <WebSocketContext.Provider
      value={{
        isConnected,
        activeAlarms,
        currentAlarm: activeAlarms[0] || null,
        displayTest,
        testDisplay,
        closeDisplayTest: () => setDisplayTest(null),
        testConnection,
        dismissCurrentAlarm,
        audioReady,
        audioError,
        unlockAudio,
        activationError,
        retryConnection,
        sessionConflict,
        stationConfig,
        saveStationConfig,
        lastAck,
        recentStatusEvents,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocket() {
  const context = useContext(WebSocketContext);
  if (!context) throw new Error('useWebSocket must be used within WebSocketProvider');
  return context;
}
