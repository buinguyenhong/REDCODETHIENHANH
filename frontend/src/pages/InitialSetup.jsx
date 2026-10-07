import { useState } from 'react';

export default function InitialSetup() {
  const [token, setToken] = useState('');
  const [url, setUrl] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (complete) => {
    setBusy(true);
    try {
      const response = await fetch(`/api/setup/${complete ? 'complete' : 'test'}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Setup-Token': token }, body: JSON.stringify({ database_url: url, admin_password: password }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Kiểm tra thông tin nhập');
      setMessage(complete ? 'Đã thiết lập. Đang khởi động; tải lại trang sau vài giây và đăng nhập admin.' : 'Kết nối PostgreSQL thành công.');
      if (complete) setTimeout(() => window.location.reload(), 6000);
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  return <main className="max-w-2xl mx-auto p-8 space-y-5"><h1 className="text-2xl font-bold">Thiết lập REDCODE</h1><p>Chưa kết nối database. Nhập PostgreSQL hiện có để migrate và tạo Admin. n8n có thể cấu hình sau trong Admin.</p><p>IT lấy mã cài đặt trên server: <code>docker compose exec backend cat /app/config/setup-token</code></p><label className="block">Mã cài đặt<input type="password" className="block border p-3 w-full" value={token} onChange={e => setToken(e.target.value)} /></label><label className="block">PostgreSQL URL<input type="password" placeholder="postgresql+asyncpg://user:password@host:5432/redcode" className="block border p-3 w-full" value={url} onChange={e => setUrl(e.target.value)} /></label><label className="block">Mật khẩu Admin đầu tiên (ít nhất 12 ký tự)<input type="password" className="block border p-3 w-full" value={password} onChange={e => setPassword(e.target.value)} /></label><div className="flex gap-3"><button disabled={busy} className="border p-3" onClick={() => submit(false)}>KIỂM TRA KẾT NỐI</button><button disabled={busy} className="bg-red-700 text-white p-3" onClick={() => submit(true)}>MIGRATE VÀ HOÀN TẤT</button></div><p role="status">{message}</p></main>;
}
