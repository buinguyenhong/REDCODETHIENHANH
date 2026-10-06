import { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { soundPlayer } from '../utils/soundPlayer';
import { api } from '../api/client';
import { useAuth } from './AuthContext';

const WebSocketContext = createContext(null);

export function WebSocketProvider({ children }) {
  const { token } = useAuth();
  const [isConnected, setIsConnected] = useState(false);
  const [activeAlarms, setActiveAlarms] = useState([]); // FIFO queue of active alarms
  const [audioReady, setAudioReady] = useState(false);
  const [lastAck, setLastAck] = useState(null);
  const [recentStatusEvents, setRecentStatusEvents] = useState([]);

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
  const dismissedRef = useRef(new Set(JSON.parse(localStorage.getItem('redcode_pending_dismiss') || '[]').map(item => item.alarm_id)));
  const ordered = (alarms) => [...new Map(alarms.filter(a => !dismissedRef.current.has(a.alarm_id)).map(a => [a.alarm_id, a])).values()].sort((a,b) => a.server_sequence - b.server_sequence);

  const saveStationConfig = (config) => {
    setStationConfig(config);
    if (config) {
      localStorage.setItem('redcode_station_config', JSON.stringify(config));
    } else {
      localStorage.removeItem('redcode_station_config');
    }
  };

  const synchronize = async () => {
    if (!stationConfig?.device_token) return;
    const socket = wsRef.current;
    const startedAt = Date.now();
    const pending = JSON.parse(localStorage.getItem('redcode_pending_dismiss') || '[]');
    const remaining = [];
    for (const item of pending) {
      try { await api.dismissStationAlarm(item); } catch (_) { remaining.push(item); }
    }
    localStorage.setItem('redcode_pending_dismiss', JSON.stringify(remaining));
    const alarms = await api.getStationActiveAlarms(stationConfig.station_code, stationConfig.device_token);
    if (disposedRef.current || wsRef.current !== socket) return;
    const ids = new Set(alarms.map(a => a.alarm_id));
    setActiveAlarms(prev => ordered([...prev.filter(a => ids.has(a.alarm_id) || a.localReceivedAt >= startedAt), ...alarms]));
    for (const alarm of alarms) {
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: 'STATION_EVENT', event_type: 'RECEIVED', alarm_id: alarm.alarm_id }));
    }
  };

  const connect = useCallback(() => {
    if (disposedRef.current || (!stationConfig?.device_token && !token)) return;
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
        console.log('[WebSocket] Kết nối thành công tới máy chủ Redcode');

        // Sync missed/active alarms for this station on connect/reconnect
        if (stationConfig && stationConfig.station_code) {
          synchronize().catch((err) => console.warn('Lỗi đồng bộ:', err));
        }

        // Start heartbeat every 5 seconds
        if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            if (Date.now() - lastHeartbeatAckRef.current > 20000) { ws.close(); return; }
            ws.send(JSON.stringify({
              type: 'HEARTBEAT',
              audio_ready: soundPlayer.isAudioReady,
              client_ready: true,
            }));
          }
        }, 5000);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          handleIncomingMessage(msg);
        } catch (e) {
          console.error('[WebSocket] Lỗi xử lý tin nhắn:', e);
        }
      };

      ws.onclose = () => {
        if (disposedRef.current || wsRef.current !== ws) return;
        setIsConnected(false);
        if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
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

  const scheduleReconnect = () => {
    if (disposedRef.current) return;
    if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    const delay = Math.min(1000 * Math.pow(1.5, reconnectAttemptsRef.current), 10000);
    reconnectAttemptsRef.current++;
    reconnectTimeoutRef.current = setTimeout(() => {
      console.log(`[WebSocket] Thử kết nối lại (lần ${reconnectAttemptsRef.current})...`);
      connect();
    }, delay);
  };

  const handleIncomingMessage = (msg) => {
    switch (msg.type) {
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
        if (msg.alarm_id) {
          dismissedRef.current.add(msg.alarm_id);
          setActiveAlarms((prev) => prev.filter((a) => a.alarm_id !== msg.alarm_id));
        }
        break;

      case 'AUDIO_TEST':
        console.log('[WebSocket] Nhận lệnh kiểm tra âm thanh từ Admin');
        soundPlayer.playTestTone().then(() => setAudioReady(true)).catch(() => setAudioReady(false));
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
    if (activeAlarms.length > 0) {
      const currentAlarm = activeAlarms[0];
      if (wsRef.current?.readyState === WebSocket.OPEN && stationConfig?.station_code) wsRef.current.send(JSON.stringify({ type: 'STATION_EVENT', event_type: 'DISPLAYED', alarm_id: currentAlarm.alarm_id }));
      if (currentAlarm.audio_sequence && currentAlarm.audio_sequence.length > 0) {
        soundPlayer.playAlarmSequence(
          currentAlarm.audio_sequence,
          currentAlarm.repeat_count || 4,
          currentAlarm.repeat_interval_ms || 1200,
          () => {
            // onStart: Send AUDIO_STARTED audit event
            setAudioReady(true);
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
    connect();
    return () => {
      disposedRef.current = true;
      if (wsRef.current) wsRef.current.onclose = null;
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
    };
  }, [connect]);

  return (
    <WebSocketContext.Provider
      value={{
        isConnected,
        activeAlarms,
        currentAlarm: activeAlarms[0] || null,
        dismissCurrentAlarm,
        audioReady,
        unlockAudio,
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
