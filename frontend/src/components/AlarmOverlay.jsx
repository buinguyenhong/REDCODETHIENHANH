import { AlertOctagon, Volume2, CheckCircle2, ChevronRight, Clock, MapPin } from 'lucide-react';
import { useWebSocket } from '../context/WebSocketContext';

export default function AlarmOverlay() {
  const { currentAlarm: realAlarm, displayTest, closeDisplayTest, activeAlarms, dismissCurrentAlarm, audioReady, audioError, unlockAudio } = useWebSocket();
  const currentAlarm = realAlarm || displayTest;

  if (!currentAlarm) return null;

  const isRed = currentAlarm.code?.includes('RED') || currentAlarm.display_color === '#dc2626';
  const bgColor = currentAlarm.display_color || (isRed ? '#dc2626' : '#2563eb');

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-between overflow-y-auto p-4 md:p-12 text-white select-none"
      style={{ backgroundColor: bgColor }}
    >
      {/* Top Banner: Audio Status & Queue indicator */}
      <div className="flex items-center justify-between border-b-2 border-white/30 pb-4">
        <div className="flex items-center space-x-3">
          <span className="flex h-4 w-4 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
            <span className="relative inline-flex rounded-full h-4 w-4 bg-yellow-300"></span>
          </span>
          <span className="font-mono text-sm md:text-base font-bold uppercase tracking-widest text-white/90">
            TÍN HIỆU CẢNH BÁO Y TẾ KHẨN CẤP
          </span>
        </div>

        {/* Audio unlock button if autoplay was blocked */}
        {!audioReady && !currentAlarm.isTest && (
          <button
            onClick={unlockAudio}
            className="flex items-center space-x-2 bg-yellow-400 text-slate-900 px-5 py-2.5 rounded-lg font-black text-sm uppercase shadow-2xl hover:bg-yellow-300 animate-bounce active:scale-95"
          >
            <Volume2 className="w-5 h-5" />
            <span>Chạm để bật còi hú</span>
          </button>
        )}

        {/* FIFO Queue badge if multiple alerts */}
        {activeAlarms.length > 1 && (
          <div className="bg-black/50 px-4 py-2 rounded-lg font-mono text-sm font-bold text-yellow-300 border border-yellow-400/40">
            Hàng đợi: 1 / {activeAlarms.length} báo động
          </div>
        )}
      </div>

      {audioError && !currentAlarm.isTest && <p role="alert" className="font-bold border-2 border-yellow-300 p-3">Lỗi âm thanh: {audioError}. Kiểm tra loa và chạm để thử bật còi lại.</p>}

      {/* Center Body: Massive Alarm Typography */}
      <div className="flex-1 flex flex-col justify-center items-center text-center my-6 max-w-5xl mx-auto w-full">
        <AlertOctagon className="w-24 h-24 md:w-36 md:h-36 text-yellow-300 mb-4 animate-pulse-subtle drop-shadow-2xl" />

        <div className="text-5xl md:text-8xl font-black uppercase tracking-wider mb-4 drop-shadow-[0_4px_12px_rgba(0,0,0,0.5)]">
          {currentAlarm.code}
        </div>

        <div className="text-2xl md:text-4xl font-bold uppercase text-yellow-200 mb-6 tracking-wide drop-shadow">
          {currentAlarm.name}
        </div>

        <div className="w-full bg-black/40 p-4 md:p-8 border-2 border-white/20 space-y-4 text-left">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex items-start space-x-3">
              <MapPin className="w-6 h-6 text-yellow-300 shrink-0 mt-1" />
              <div>
                <span className="text-xs uppercase font-mono text-slate-300 block">KHOA / PHÒNG BAN:</span>
                <span className="text-xl md:text-2xl font-black text-white">{currentAlarm.department}</span>
              </div>
            </div>

            <div className="flex items-start space-x-3">
              <Clock className="w-6 h-6 text-yellow-300 shrink-0 mt-1" />
              <div>
                <span className="text-xs uppercase font-mono text-slate-300 block">THỜI GIAN PHÁT:</span>
                <span className="text-lg md:text-xl font-mono font-bold text-white">
                  {new Date(currentAlarm.created_at).toLocaleTimeString('vi-VN')}
                </span>
              </div>
            </div>
          </div>

          <div className="border-t border-white/20 pt-4">
            <span className="text-xs uppercase font-mono text-slate-300 block">VỊ TRÍ CHI TIẾT & GHI CHÚ:</span>
            <div className="text-xl md:text-3xl font-extrabold text-white mt-1 bg-white/10 p-4 rounded-xl border border-white/15">
              {currentAlarm.location || currentAlarm.department}
              {currentAlarm.note ? ` — "${currentAlarm.note}"` : ''}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Action: Big Touch Dismiss Button */}
      <div className="w-full max-w-3xl mx-auto">
        <button
          onClick={() => currentAlarm.isTest ? closeDisplayTest() : dismissCurrentAlarm('Bác sĩ/Điều dưỡng trực xác nhận')}
          className="w-full py-5 md:py-7 bg-white text-slate-950 font-black text-2xl md:text-3xl uppercase tracking-wider rounded-2xl shadow-[0_10px_30px_rgba(0,0,0,0.6)] hover:bg-slate-100 active:scale-[0.98] transition flex items-center justify-center space-x-3 border-b-8 border-slate-300"
        >
          <CheckCircle2 className="w-8 h-8 md:w-10 md:h-10 text-emerald-600" />
          <span>{currentAlarm.isTest ? 'KẾT THÚC KIỂM TRA' : 'TẮT CẢNH BÁO TẠI ĐÂY (DISMISS)'}</span>
        </button>
        <p className="text-center text-xs md:text-sm text-white/80 font-mono mt-3">
          * Thao tác tắt báo động chỉ áp dụng cho trạm này (Local Dismiss). Không tắt còi ở các khoa khác.
        </p>
      </div>
    </div>
  );
}
