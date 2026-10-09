import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { api } from '../api/client';
import { randomId } from '../utils/uuid';
import { Bell, Clock, MapPin, CheckCircle, ShieldAlert, History, XCircle, AlertCircle } from 'lucide-react';

export default function OperatorDashboard() {
  const { user } = useAuth();
  const { isConnected, recentStatusEvents } = useWebSocket();
  const [alarmTypes, setAlarmTypes] = useState([]);
  const [selectedType, setSelectedType] = useState(null);
  const [location, setLocation] = useState('');
  const [note, setNote] = useState('');
  const [sending, setSending] = useState(false);
  const [recentAlarms, setRecentAlarms] = useState([]);
  const [statusMessage, setStatusMessage] = useState(null);
  const requestRef = useRef(null);

  useEffect(() => {
    loadAlarmTypes();
    loadRecentAlarms();
    const interval = setInterval(loadRecentAlarms, 6000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (recentStatusEvents[0]?.type === 'ALARM_CANCELLED' || recentStatusEvents[0]?.type === 'ALARM_EXPIRED') loadRecentAlarms();
  }, [recentStatusEvents]);

  const isPermitted = (type) => {
    return ['ADMIN', 'OPERATOR'].includes(user?.role);
  };

  const loadAlarmTypes = async () => {
    try {
      const data = await api.getPermittedAlarmTypes();
      setAlarmTypes(data);
      const permitted = data;
      if (permitted.length > 0 && (!selectedType || !permitted.some((p) => p.id === selectedType.id))) {
        setSelectedType(permitted[0]);
      }
    } catch (e) {
      console.error('Lỗi tải danh mục báo động:', e);
    }
  };

  const loadRecentAlarms = async () => {
    try {
      const data = await api.getAlarms(null, 15);
      setRecentAlarms(data);
    } catch (e) {
      console.error('Lỗi tải nhật ký báo động:', e);
    }
  };

  const handleTriggerAlarm = async () => {
    if (!selectedType || sending) return;

    const confirmText = `[XÁC NHẬN PHÁT CẢNH BÁO]\nBạn có chắc chắn muốn kích hoạt: ${selectedType.name}?\nĐịa điểm: ${location || user?.department?.name || 'Toàn viện'}`;
    if (!window.confirm(confirmText)) return;

    setSending(true);
    setStatusMessage(null);

    try {
      const payload = {
        alarm_type_id: selectedType.id,
        source_department_id: user?.department_id,
        source_location: location.trim() || user?.department?.name || 'Toàn viện',
        note: note.trim() || selectedType.description || '',
      };
      const fingerprint = JSON.stringify(payload);
      if (requestRef.current?.fingerprint !== fingerprint) requestRef.current = { fingerprint, key: randomId() };
      await api.createAlarm({ ...payload, idempotency_key: requestRef.current.key });
      requestRef.current = null;

      setStatusMessage({
        type: 'success',
        text: `Đã phát thành công tín hiệu ${selectedType.code} tới các trạm nhận!`,
      });
      setLocation('');
      setNote('');
      loadRecentAlarms();
    } catch (err) {
      setStatusMessage({
        type: 'error',
        text: `Lỗi phát cảnh báo: ${err.message}`,
      });
    } finally {
      setSending(false);
    }
  };

  const handleCancelAlarm = async (alarmId) => {
    if (!window.confirm('Bạn có chắc chắn muốn HỦY báo động này?')) return;
    try {
      await api.cancelAlarm(alarmId);
      loadRecentAlarms();
    } catch (err) {
      alert('Lỗi hủy báo động: ' + err.message);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 p-4 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Status Alert if any */}
        {statusMessage && (
          <div
            className={`p-4 rounded-xl border flex items-center justify-between ${
              statusMessage.type === 'success'
                ? 'bg-emerald-50 border-emerald-300 text-emerald-800'
                : 'bg-red-50 border-red-300 text-red-800'
            }`}
          >
            <div className="flex items-center space-x-3">
              <CheckCircle className="w-5 h-5 shrink-0 text-emerald-600" />
              <span className="font-semibold text-sm">{statusMessage.text}</span>
            </div>
            <button
              onClick={() => setStatusMessage(null)}
              className="text-xs uppercase font-bold hover:underline"
            >
              Đóng
            </button>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Dispatch Control Console */}
          <div className="lg:col-span-8 space-y-6">
            <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-sm">
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-100">
                <div className="flex items-center space-x-3">
                  <div className="p-2.5 bg-red-50 text-red-600 rounded-xl border border-red-100">
                    <ShieldAlert className="w-6 h-6" />
                  </div>
                  <div>
                    <h2 className="text-xl font-black uppercase tracking-wide text-slate-900">
                      BẢNG ĐIỀU KHIỂN PHÁT REDCODE
                    </h2>
                    <p className="text-xs text-slate-500 font-mono">
                      Khoa trực: <span className="text-slate-800 font-bold">{user?.department?.name || 'Chung'}</span>
                    </p>
                  </div>
                </div>

                {!isConnected && (
                  <span className="bg-red-50 text-red-600 border border-red-200 px-3 py-1 rounded-full text-xs font-mono font-bold animate-pulse">
                    MẤT KẾT NỐI LAN
                  </span>
                )}
              </div>

              {/* 1. Alarm Types Selection Grid */}
              <div className="mb-6">
                <label className="block text-xs font-mono font-bold uppercase text-slate-500 mb-3 tracking-wider">
                  BƯỚC 1: CHỌN MÃ BÁO ĐỘNG KHẨN CẤP
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {alarmTypes.map((type) => {
                    const isSelected = selectedType?.id === type.id;
                    const hasPermission = isPermitted(type);
                    return (
                      <button
                        key={type.id}
                        type="button"
                        disabled={!hasPermission}
                        onClick={() => hasPermission && setSelectedType(type)}
                        className={`p-5 rounded-xl text-left transition-all border-2 flex flex-col justify-between ${
                          !hasPermission
                            ? 'opacity-50 cursor-not-allowed bg-slate-100 border-slate-200'
                            : isSelected
                            ? 'border-red-600 bg-red-50/40 shadow-md ring-2 ring-red-100 scale-[1.01]'
                            : 'border-slate-200 bg-slate-50/60 hover:border-slate-300 hover:bg-slate-100/70'
                        }`}
                      >
                        <div className="flex items-center justify-between w-full mb-2">
                          <span
                            className="px-2.5 py-1 rounded font-black text-xs font-mono tracking-wider text-white shadow-sm"
                            style={{ backgroundColor: type.display_color || '#dc2626' }}
                          >
                            {type.code}
                          </span>
                          {isSelected && (
                            <CheckCircle className="w-5 h-5 text-red-600" />
                          )}
                          {!hasPermission && (
                            <span className="text-[10px] font-bold text-amber-700 bg-amber-100 px-2 py-0.5 rounded">
                              KHÔNG ĐỦ QUYỀN
                            </span>
                          )}
                        </div>
                        <div className="font-bold text-slate-900 text-base md:text-lg mb-1">{type.name}</div>
                        <div className="text-xs text-slate-500 line-clamp-2">{type.description}</div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* 2. Location & Note Input */}
              <div className="space-y-4 mb-8">
                <div>
                  <label className="block text-xs font-mono font-bold uppercase text-slate-600 mb-2 tracking-wider">
                    BƯỚC 2: VỊ TRÍ XẢY RA SỰ CỐ
                  </label>
                  <div className="relative">
                    <MapPin className="w-5 h-5 text-slate-400 absolute left-3.5 top-3.5" />
                    <input
                      type="text"
                      value={location}
                      onChange={(e) => setLocation(e.target.value)}
                      placeholder={`Ví dụ: Phòng cấp cứu số 3, Giường 05 (${user?.department?.name || 'Khoa'})`}
                      className="w-full bg-slate-50 border border-slate-300 rounded-xl py-3 pl-11 pr-4 text-slate-900 text-base focus:border-red-500 focus:bg-white focus:outline-none transition"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-mono font-bold uppercase text-slate-600 mb-2 tracking-wider">
                    BƯỚC 3: GHI CHÚ BỔ SUNG (TÙY CHỌN)
                  </label>
                  <input
                    type="text"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Ví dụ: Bệnh nhân nam 45T ngừng tuần hoàn sau sốc phản vệ"
                    className="w-full bg-slate-50 border border-slate-300 rounded-xl py-3 px-4 text-slate-900 text-sm focus:border-red-500 focus:bg-white focus:outline-none transition"
                  />
                </div>
              </div>

              {/* 3. Dispatch Big Action Button (With Double-Click Protection) */}
              <button
                type="button"
                disabled={sending || !selectedType}
                onClick={handleTriggerAlarm}
                className="w-full py-5 md:py-6 bg-red-600 hover:bg-red-700 active:scale-[0.98] text-white font-black text-2xl md:text-3xl uppercase tracking-wider rounded-xl shadow-lg shadow-red-200 transition flex items-center justify-center space-x-4 disabled:opacity-50 disabled:cursor-not-allowed border-b-4 border-red-800"
              >
                <Bell className="w-7 h-7 md:w-8 md:h-8 animate-bounce" />
                <span>{sending ? 'ĐANG KÍCH HOẠT...' : `PHÁT TÍN HIỆU ${selectedType?.code || 'REDCODE'}`}</span>
              </button>
            </div>
          </div>

          {/* Right: Live Recent Logs */}
          <div className="lg:col-span-4 space-y-6">
            <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm flex flex-col h-full max-h-[800px]">
              <div className="flex items-center justify-between pb-4 border-b border-slate-100 mb-4">
                <div className="flex items-center space-x-2 text-slate-800 font-bold text-base">
                  <History className="w-5 h-5 text-slate-500" />
                  <span>NHẬT KÝ BÁO ĐỘNG GẦN ĐÂY</span>
                </div>
                <button
                  onClick={loadRecentAlarms}
                  className="text-xs font-mono text-red-600 hover:underline font-bold"
                >
                  Làm mới
                </button>
              </div>

              <div className="space-y-3 overflow-y-auto flex-1 pr-1">
                {recentAlarms.map((alarm) => {
                  const isActive = alarm.status === 'ACTIVE';
                  return (
                    <div
                      key={alarm.id}
                      className={`p-4 rounded-xl border transition ${
                        isActive
                          ? 'bg-red-50/60 border-red-200 shadow-sm'
                          : 'bg-slate-50/60 border-slate-200'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span
                          className="px-2 py-0.5 rounded font-black text-xs font-mono text-white"
                          style={{ backgroundColor: alarm.alarm_type?.display_color || '#dc2626' }}
                        >
                          {alarm.alarm_type?.code || 'REDCODE'}
                        </span>
                        <span className="text-xs font-mono text-slate-500 flex items-center space-x-1">
                          <Clock className="w-3.5 h-3.5" />
                          <span>{new Date(alarm.created_at).toLocaleTimeString('vi-VN')}</span>
                        </span>
                      </div>

                      <div className="text-sm font-bold text-slate-900 mb-1">
                        {alarm.source_department?.name || 'Khoa'}
                      </div>
                      <div className="text-xs text-slate-600 font-medium mb-2">
                        {alarm.source_location}
                        {alarm.note ? ` — "${alarm.note}"` : ''}
                      </div>

                      <div className="flex items-center justify-between pt-2 border-t border-slate-200/80 text-xs">
                        <span
                          className={`font-mono font-bold flex items-center space-x-1.5 ${
                            isActive ? 'text-red-600 animate-pulse' : 'text-slate-500'
                          }`}
                        >
                          <span
                            className={`w-2 h-2 rounded-full ${
                              isActive ? 'bg-red-600' : 'bg-slate-400'
                            }`}
                          ></span>
                          <span>{isActive ? 'ĐANG BÁO ĐỘNG' : alarm.status === 'EXPIRED' ? 'CẢNH BÁO ĐÃ PHÁT' : 'ĐÃ HỦY'}</span>
                        </span>

                        {isActive && (
                          <button
                            onClick={() => handleCancelAlarm(alarm.id)}
                            className="text-red-600 hover:text-red-800 hover:underline flex items-center space-x-1 font-bold"
                          >
                            <XCircle className="w-3.5 h-3.5" />
                            <span>Hủy</span>
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}

                {recentAlarms.length === 0 && (
                  <p className="text-slate-400 text-center py-12 text-sm font-mono">
                    Chưa có nhật ký báo động
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
