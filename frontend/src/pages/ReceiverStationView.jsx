import { useState, useEffect } from 'react';
import { useWebSocket } from '../context/WebSocketContext';
import { api } from '../api/client';
import { Monitor, Radio, Volume2, VolumeX, Maximize2, Minimize2, Settings, ShieldCheck, CheckCircle2 } from 'lucide-react';

export default function ReceiverStationView() {
  const { isConnected, audioReady, unlockAudio, stationConfig, saveStationConfig } = useWebSocket();
  const [stationsList, setStationsList] = useState([]);
  const [showConfig, setShowConfig] = useState(!stationConfig);
  const [selectedStationCode, setSelectedStationCode] = useState(stationConfig?.station_code || '');
  const [deviceToken, setDeviceToken] = useState(stationConfig?.device_token || '');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    if (localStorage.getItem('redcode_token')) loadStations();
  }, []);

  const loadStations = async () => {
    try {
      const data = await api.getStations();
      setStationsList(data);
    } catch (e) {
      console.error('Lỗi tải danh sách trạm:', e);
    }
  };

  const handleSaveConfig = async () => {
    const token = deviceToken.trim();
    if (!token) {
      alert('Vui lòng nhập Device Activation Token bảo mật do Quản trị viên cấp');
      return;
    }
    let found;
    try { found = await api.activateStation({ station_code: selectedStationCode, device_token: token }); }
    catch (error) { alert(error.message); return; }
    saveStationConfig({
      station_code: found.station_code,
      name: found.name,
      department: found.department?.name,
      location: found.location,
      device_token: token,
    });
    setShowConfig(false);
    window.location.reload();
  };

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().then(() => setIsFullscreen(true)).catch((e) => console.log(e));
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch((e) => console.log(e));
    }
  };

  const runLocalSoundTest = async () => {
    const ok = await unlockAudio();
    if (ok) {
      setTestResult('Âm thanh đã kích hoạt thành công!');
      setTimeout(() => setTestResult(null), 4000);
    } else {
      setTestResult('Trình duyệt chưa cho phép tự phát âm thanh. Vui lòng bấm tương tác lại.');
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col justify-between p-4 md:p-8">
      {/* Top Station Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white border border-slate-200 p-5 rounded-2xl shadow-sm">
        <div className="flex items-center space-x-3.5">
          <div className="bg-red-50 text-red-600 p-3 rounded-xl border border-red-100">
            <Monitor className="w-7 h-7" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-black text-slate-900 uppercase tracking-wider">
                {stationConfig?.name || 'TRẠM NHẬN REDCODE'}
              </h1>
              <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-bold border border-slate-200">
                {stationConfig?.station_code || 'CHƯA ĐỊNH DANH'}
              </span>
            </div>
            <p className="text-xs text-slate-500 font-mono mt-0.5">
              Khoa: <span className="text-slate-800 font-bold">{stationConfig?.department || 'Tất cả'}</span> —{' '}
              {stationConfig?.location || 'Màn hình trực'}
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center space-x-3 self-end sm:self-center">
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="p-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl border border-slate-200 transition"
            title="Cấu hình trạm"
          >
            <Settings className="w-5 h-5" />
          </button>

          <button
            onClick={toggleFullscreen}
            className="p-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl border border-slate-200 transition"
            title="Chế độ toàn màn hình Kiosk"
          >
            {isFullscreen ? <Minimize2 className="w-5 h-5" /> : <Maximize2 className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Configuration Modal */}
      {showConfig && (
        <div className="my-6 p-6 bg-white border border-slate-200 rounded-2xl shadow-xl max-w-xl mx-auto w-full">
          <h2 className="text-lg font-bold text-slate-900 mb-4 uppercase tracking-wide">
            CẤU HÌNH THIẾT BỊ / TRẠM NHẬN (KIOSK IDENTIFICATION)
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-mono font-bold uppercase text-slate-600 mb-2">
                Chọn trạm cố định trong hệ thống:
              </label>
              <input list="station-options"
                value={selectedStationCode}
                onChange={(e) => setSelectedStationCode(e.target.value)}
                className="w-full bg-slate-50 border border-slate-300 rounded-xl p-3 text-slate-900 font-mono text-sm focus:border-red-500 focus:bg-white focus:outline-none"
              />
              <datalist id="station-options">
                {stationsList.map((s) => (
                  <option key={s.id} value={s.station_code}>
                    {s.station_code} — {s.name} ({s.department?.name || 'Toàn viện'})
                  </option>
                ))}
              </datalist>
            </div>

            <div>
              <label className="block text-xs font-mono font-bold uppercase text-slate-600 mb-2">
                Device Activation Token (Mã bảo mật thiết bị):
              </label>
              <input
                type="text"
                value={deviceToken}
                onChange={(e) => setDeviceToken(e.target.value)}
                placeholder="Nhập mã token bảo mật do Admin cấp khi khởi tạo trạm"
                className="w-full bg-slate-50 border border-slate-300 rounded-xl p-3 text-slate-900 font-mono text-sm focus:border-red-500 focus:bg-white focus:outline-none"
              />
              <p className="text-xs text-slate-500 font-mono mt-1">
                * Mã này lưu trong bộ nhớ máy trạm, giúp tự động kết nối lại sau khi mở máy hoặc khởi động lại trình duyệt.
              </p>
            </div>

            <div className="flex space-x-3 pt-2">
              <button
                onClick={handleSaveConfig}
                className="flex-1 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-sm transition shadow-sm"
              >
                LƯU VÀ KÍCH HOẠT TRẠM
              </button>
              {stationConfig && (
                <button
                  onClick={() => setShowConfig(false)}
                  className="px-4 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl text-sm transition"
                >
                  Đóng
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Main Standby Interface (Neutral, Calm, Clinical) */}
      <div className="flex-1 flex flex-col items-center justify-center text-center my-8 max-w-3xl mx-auto w-full">
        <div className="p-8 md:p-10 bg-white border border-slate-200 rounded-3xl shadow-sm w-full space-y-6">
          <div className="flex justify-center">
            <div className="p-5 bg-emerald-50 text-emerald-600 rounded-3xl border border-emerald-100">
              <ShieldCheck className="w-16 h-16 md:w-20 md:h-20" />
            </div>
          </div>

          <div>
            <span className="text-xs font-mono uppercase tracking-widest text-emerald-700 font-bold bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200">
              TRẠNG THÁI: THƯỜNG TRỰC SẴN SÀNG
            </span>
            <h2 className="text-2xl md:text-3xl font-black text-slate-900 uppercase mt-4">
              HỆ THỐNG ĐANG GIÁM SÁT REALTIME
            </h2>
            <p className="text-slate-500 text-sm mt-2 max-w-lg mx-auto">
              Khi có mã báo động Redcode phát sinh từ các khoa, màn hình sẽ tự động chuyển sang chế độ báo động khẩn cấp và phát còi hú âm lượng lớn.
            </p>
          </div>

          {/* Readiness Indicators */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-left border-t border-slate-100 pt-6">
            <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
              <span className="text-xs font-mono uppercase text-slate-500 block mb-1">KẾT NỐI WEBSOCKET LAN:</span>
              <div className="flex items-center space-x-2">
                <span className={`w-3 h-3 rounded-full ${isConnected ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
                <span className="font-bold text-slate-800 font-mono text-sm">
                  {isConnected ? 'ONLINE (ĐÃ KẾT NỐI)' : 'MẤT KẾT NỐI (ĐANG THỬ LẠI...)'}
                </span>
              </div>
            </div>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-200">
              <span className="text-xs font-mono uppercase text-slate-500 block mb-1">TRẠNG THÁI ÂM THANH (AUDIO):</span>
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className={`w-3 h-3 rounded-full ${audioReady ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'}`}></span>
                  <span className="font-bold text-slate-800 font-mono text-sm">
                    {audioReady ? 'AUDIO READY' : 'CHỜ KÍCH HOẠT'}
                  </span>
                </div>
                {!audioReady && (
                  <button
                    onClick={runLocalSoundTest}
                    className="text-xs font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded border border-amber-200 hover:bg-amber-100"
                  >
                    Bật ngay
                  </button>
                )}
              </div>
            </div>
          </div>

          {testResult && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-mono flex items-center justify-center space-x-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span>{testResult}</span>
            </div>
          )}

          <div className="pt-2">
            <button
              onClick={runLocalSoundTest}
              className="px-6 py-3 bg-slate-100 hover:bg-slate-200 active:scale-95 text-slate-700 font-bold rounded-xl border border-slate-300 text-xs font-mono tracking-wider transition flex items-center justify-center space-x-2 mx-auto"
            >
              <Volume2 className="w-4 h-4 text-emerald-600" />
              <span>KIỂM TRA ÂM THANH THỰC TẾ (TEST AUDIO)</span>
            </button>
          </div>
        </div>
      </div>

      {/* Footer Info */}
      <div className="text-center text-xs font-mono text-slate-400 border-t border-slate-200 pt-4">
        Bệnh Viện Đa Khoa Thiện Hạnh • Redcode Local Hospital LAN Protocol • 50–100 Nodes Capable
      </div>
    </div>
  );
}
