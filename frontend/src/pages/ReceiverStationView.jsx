import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { api } from '../api/client';

export default function ReceiverStationView() {
  const { user } = useAuth();
  const { stationConfig, saveStationConfig, isConnected, audioReady, unlockAudio, testDisplay, testConnection, currentAlarm } = useWebSocket();
  const [stations, setStations] = useState([]);
  const [selected, setSelected] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [changeDevice, setChangeDevice] = useState(false);
  useEffect(() => {
    if (user?.role === 'ADMIN') api.getStations().then(data => setStations(data.filter(s => s.enabled))).catch(error => setMessage(error.message));
  }, [user]);
  const confirm = async () => {
    setBusy(true);
    try {
      const station = await api.confirmDevice(Number(selected));
      saveStationConfig({ station_code: station.station_code, name: station.name, department: station.department?.name, department_id: station.department_id, location: station.location, device_token: station.raw_device_token });
      setChangeDevice(false);
      setMessage('Đã xác nhận thiết bị. Trạm sẽ tự kết nối trong các lần mở sau.');
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  const test = async (kind) => {
    try {
      if (kind === 'sound') setMessage(await unlockAudio() ? 'Đã phát âm thanh kiểm tra. Vui lòng xác nhận nghe được tại loa.' : 'Không phát được âm thanh. Kiểm tra quyền trình duyệt và loa.');
      if (kind === 'display') { testDisplay(); setMessage('Đang hiển thị cảnh báo thử, không tạo báo động thật.'); }
      if (kind === 'connection') setMessage(`Kết nối hai chiều thành công: ${await testConnection()} ms`);
    } catch (error) { setMessage(error.message); }
  };
  return <div className="min-h-screen bg-slate-50 p-4 md:p-8 text-slate-900">
    <div className="max-w-4xl mx-auto space-y-6">
      <header className="border-b border-slate-300 pb-4"><h1 className="text-2xl font-bold">TRẠM NHẬN REDCODE</h1><p>{stationConfig?.name || 'Thiết bị chưa được xác nhận'} · {stationConfig?.station_code || 'Chưa định danh'}</p><p>{stationConfig?.department} — {stationConfig?.location}</p></header>
      {(!stationConfig || changeDevice) && <section className="bg-white border p-5 space-y-3">
        <h2 className="font-bold">Xác nhận trạm trên thiết bị này</h2>
        {user?.role === 'ADMIN' ? <><p>Chọn trạm rồi xác nhận. Danh tính thiết bị được lưu tự động; kết nối cũ của trạm sẽ được thu hồi.</p><select className="w-full border p-3" value={selected} onChange={event => setSelected(event.target.value)}><option value="">Chọn trạm</option>{stations.map(station => <option key={station.id} value={station.id}>{station.station_code} — {station.name} ({station.department?.name})</option>)}</select><button disabled={!selected || busy} className="bg-red-700 text-white p-3 disabled:opacity-50" onClick={confirm}>XÁC NHẬN THIẾT BỊ NÀY</button></> : <p>Admin cần đăng nhập một lần trên máy này để xác nhận trạm. Sau đó tài khoản khoa có thể sử dụng hoặc máy chạy độc lập. {!user && <Link className="underline" to="/login">Đăng nhập Admin</Link>}</p>}
      </section>}
      <section className="bg-white border p-6 space-y-4"><h2 className="text-xl font-bold">{stationConfig && isConnected ? 'TRẠM ĐÃ KẾT NỐI' : 'TRẠM CHƯA SẴN SÀNG'}</h2><p>Kết nối: {isConnected && stationConfig ? 'ONLINE' : 'OFFLINE / CHƯA XÁC NHẬN'} · Âm thanh: {audioReady ? 'READY' : 'CHƯA KIỂM TRA'}</p><p>User: {user?.display_name || 'Receiver tự động'} {user?.department?.name}</p>
        <div className="flex flex-wrap gap-3">{[['sound', 'TEST LOA'], ['display', 'TEST HIỂN THỊ'], ['connection', 'TEST KẾT NỐI']].map(([kind, label]) => <button key={kind} disabled={!stationConfig || !!currentAlarm} className="border border-slate-400 px-4 py-3 disabled:opacity-40" onClick={() => test(kind)}>{label}</button>)}<button className="border px-4 py-3" onClick={() => document.documentElement.requestFullscreen().catch(error => setMessage(error.message))}>TOÀN MÀN HÌNH</button></div>
        {currentAlarm && <p>Có cảnh báo thật: tạm khóa thao tác test.</p>}
        {user?.role === 'ADMIN' && stationConfig && <button className="underline" onClick={() => setChangeDevice(!changeDevice)}>Đổi / xác nhận lại trạm</button>}
      </section>
      {message && <p role="status" className="border-l-4 border-slate-600 bg-white p-4">{message}</p>}
    </div>
  </div>;
}
