import { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { soundPlayer } from '../utils/soundPlayer';
import { api } from '../api/client';

const WebSocketContext = createContext(null);

export function WebSocketProvider({ children }) {
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

  const saveStationConfig = (config) => {
    setStationConfig(config);
    if (config) {
      localStorage.setItem('redcode_station_config', JSON.stringify(config));
    } else {
      localStorage.removeItem('redcode_station_config');
    }
  };

  const connect = useCallback(() => {
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
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        console.log('[WebSocket] Kết nối thành công tới máy chủ Redcode');

        // Sync missed/active alarms for this station on connect/reconnect
        if (stationConfig && stationConfig.station_code) {
          api.getStationActiveAlarms(stationConfig.station_code, stationConfig.device_token)
            .then((alarms) => {
              if (alarms && alarms.length > 0) {
                setActiveAlarms((prev) => {
                  const existingIds = new Set(prev.map((a) => a.alarm_id));
                  const newAlarms = alarms.filter((a) => !existingIds.has(a.alarm_id));
                  return [...prev, ...newAlarms];
                });
              }
            })
            .catch((err) => console.warn('Lỗi đồng bộ báo động chủ động:', err));
        }

        // Start heartbeat every 5 seconds
        if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
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
  }, [stationConfig]);

  const scheduleReconnect = () => {
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
        if (msg.event === 'ALARM_TRIGGERED' && msg.data) {
          const alarm = msg.data;
          setActiveAlarms((prev) => {
            // Avoid duplicate alarm in queue
            if (prev.some((a) => a.alarm_id === alarm.alarm_id)) return prev;
            return [...prev, alarm]; // Enqueue in FIFO order
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
          setActiveAlarms((prev) => prev.filter((a) => a.alarm_id !== msg.alarm_id));
        }
        break;

      case 'AUDIO_TEST':
        console.log('[WebSocket] Nhận lệnh kiểm tra âm thanh từ Admin');
        soundPlayer.playTestTone();
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
  }, [activeAlarms, stationConfig]);

  // Local Dismiss of current alarm
  const dismissCurrentAlarm = async (note = '') => {
    if (activeAlarms.length === 0) return;
    const currentAlarm = activeAlarms[0];

    soundPlayer.stop();

    // Remove from local queue immediately
    setActiveAlarms((prev) => prev.slice(1));

    // Send local dismissal to backend
    if (stationConfig && stationConfig.station_code) {
      try {
        await api.dismissStationAlarm({
          alarm_id: currentAlarm.alarm_id,
          station_code: stationConfig.station_code,
          device_token: stationConfig.device_token,
          note,
        });
      } catch (err) {
        console.warn('Gửi xác nhận tắt báo động lỗi:', err);
      }
    }
  };

  const unlockAudio = async () => {
    const success = await soundPlayer.unlockAudio();
    setAudioReady(success);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'AUDIO_STATE_CHANGED',
        audio_ready: success,
      }));
    }
    return success;
  };

  useEffect(() => {
    connect();
    return () => {
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
        audioReady: soundPlayer.isAudioReady,
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
