import { useEffect, useState } from 'react';

export default function IntegrationSettings() {
  const [settings, setSettings] = useState({ enabled: false, webhook_url: '', timeout_seconds: 4, max_retries: 3 });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const request = async (path, method = 'GET') => {
    const response = await fetch(`/api/settings/n8n${path}`, { method, headers: { 'Authorization': `Bearer ${localStorage.getItem('redcode_token')}`, 'Content-Type': 'application/json' }, ...(method !== 'GET' ? { body: JSON.stringify(settings) } : {}) });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Cấu hình không hợp lệ');
    return result;
  };
  useEffect(() => { request('').then(setSettings).catch(error => setMessage(error.message)); }, []);
  const action = async test => {
    setBusy(true);
    try { const result = await request(test ? '/test' : '', test ? 'POST' : 'PUT'); setMessage(test ? (result.success ? 'Webhook phản hồi thành công' : 'Webhook lỗi hoặc không phản hồi') : 'Đã lưu cấu hình. Chỉ alarm mới khi bật tích hợp tạo outbox.'); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  return <main className="max-w-3xl mx-auto p-8 space-y-5"><h1 className="text-2xl font-bold">Cài đặt tích hợp n8n</h1><p>Có thể bỏ qua n8n. Khi tắt, cảnh báo nội bộ vẫn hoạt động và không tạo thông báo chờ gửi. Lần bật đầu không gửi lịch sử cũ.</p><label className="block"><input type="checkbox" checked={settings.enabled} onChange={e => setSettings({ ...settings, enabled: e.target.checked })} /> Bật tích hợp</label><label className="block">Webhook URL<input className="block border p-3 w-full" value={settings.webhook_url} onChange={e => setSettings({ ...settings, webhook_url: e.target.value })} /></label>{[['timeout_seconds', 'Timeout (1–30 giây)'], ['max_retries', 'Số lần thử (1–10)']].map(([key, label]) => <label key={key} className="block">{label}<input type="number" className="block border p-3" value={settings[key]} onChange={e => setSettings({ ...settings, [key]: Number(e.target.value) })} /></label>)}<p>Kiểm tra gửi event REDCODE_CONNECTION_TEST; cấu hình workflow để không coi đây là alarm thật. Không thêm credential vào URL user/password.</p><div className="flex gap-3"><button disabled={busy} className="border p-3" onClick={() => action(true)}>KIỂM TRA WEBHOOK</button><button disabled={busy} className="bg-red-700 text-white p-3" onClick={() => action(false)}>LƯU</button></div><p role="status">{message}</p></main>;
}
