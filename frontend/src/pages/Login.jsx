import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ShieldAlert, Lock, User, AlertCircle, ArrowRight } from 'lucide-react';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(username, password);
      navigate('/');
    } catch (err) {
      setError(err.message || 'Đăng nhập thất bại');
    } finally {
      setLoading(false);
    }
  };

  const setPreset = (u, p) => {
    setUsername(u);
    setPassword(p);
  };

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl p-8 shadow-xl">
        <div className="text-center mb-8">
          <div className="inline-flex p-3 bg-red-50 text-red-600 rounded-2xl mb-3 border border-red-100 shadow-sm">
            <ShieldAlert className="w-12 h-12" />
          </div>
          <h1 className="text-2xl font-black tracking-wide text-slate-900">REDCODE HOSPITAL</h1>
          <p className="text-xs text-slate-500 mt-1 uppercase tracking-widest font-mono">
            Hệ Thống Báo Động Y Tế Khẩn Cấp • Bệnh Viện Thiện Hạnh
          </p>
        </div>

        {error && (
          <div className="mb-6 p-3.5 bg-red-50 border border-red-200 rounded-xl flex items-center space-x-3 text-red-700 text-sm">
            <AlertCircle className="w-5 h-5 shrink-0 text-red-500" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-xs font-mono font-bold uppercase text-slate-600 mb-1.5">
              Tên Đăng Nhập (Username)
            </label>
            <div className="relative">
              <User className="w-5 h-5 text-slate-400 absolute left-3.5 top-3.5" />
              <input
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin hoặc operator_cc"
                className="w-full bg-slate-50 border border-slate-300 rounded-xl py-3 pl-11 pr-4 text-slate-900 text-sm focus:border-red-500 focus:bg-white focus:outline-none transition font-mono"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono font-bold uppercase text-slate-600 mb-1.5">
              Mật Khẩu (Password)
            </label>
            <div className="relative">
              <Lock className="w-5 h-5 text-slate-400 absolute left-3.5 top-3.5" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-slate-50 border border-slate-300 rounded-xl py-3 pl-11 pr-4 text-slate-900 text-sm focus:border-red-500 focus:bg-white focus:outline-none transition"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3.5 bg-red-600 hover:bg-red-700 active:scale-[0.99] text-white font-bold rounded-xl shadow-lg shadow-red-200 transition flex items-center justify-center space-x-2 text-sm disabled:opacity-50 mt-6"
          >
            <span>{loading ? 'Đang xác thực...' : 'ĐĂNG NHẬP HỆ THỐNG'}</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>

        {/* Shortcut Demo Accounts */}
        <div className="mt-8 pt-6 border-t border-slate-100">
          <p className="text-xs font-mono text-slate-400 mb-3 text-center uppercase tracking-wider">
            Tài khoản mẫu thử nghiệm:
          </p>
          <div className="grid grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => setPreset('admin', 'admin123456')}
              className="p-2.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-xl text-xs font-mono text-center text-slate-700 transition"
            >
              <span className="font-bold text-red-600 block">Admin</span>
              admin
            </button>
            <button
              type="button"
              onClick={() => setPreset('operator_cc', 'pass123456')}
              className="p-2.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-xl text-xs font-mono text-center text-slate-700 transition"
            >
              <span className="font-bold text-amber-600 block">Cấp Cứu</span>
              operator_cc
            </button>
            <button
              type="button"
              onClick={() => setPreset('operator_hscc', 'pass123456')}
              className="p-2.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-xl text-xs font-mono text-center text-slate-700 transition"
            >
              <span className="font-bold text-blue-600 block">Hồi Sức</span>
              operator_hscc
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
