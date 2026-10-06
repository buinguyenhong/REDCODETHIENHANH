import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { ShieldAlert, Activity, Monitor, BarChart3, Settings, LogOut, Radio, Volume2, VolumeX } from 'lucide-react';

export default function Navigation() {
  const { user, logout } = useAuth();
  const { isConnected, audioReady, unlockAudio } = useWebSocket();
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Bảng Điều Khiển & Log', icon: Activity, roles: ['ADMIN', 'OPERATOR'] },
    { path: '/kiosk', label: 'Màn Hình Trạm Nhận', icon: Monitor, roles: ['ADMIN', 'OPERATOR'] },
    { path: '/admin', label: 'Quản Trị & Cấu Hình', icon: Settings, roles: ['ADMIN'] },
    { path: '/reports', label: 'Báo Cáo & Xuất File', icon: BarChart3, roles: ['ADMIN'] },
  ];

  const allowedNav = navItems.filter((item) => !user || item.roles.includes(user.role));

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-40 px-4 md:px-8 py-2.5 shadow-sm">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-3">
        {/* Brand */}
        <div className="flex items-center space-x-3 w-full md:w-auto justify-between md:justify-start">
          <div className="flex items-center space-x-2.5">
            <div className="bg-red-600 p-2 rounded-lg text-white shadow-md shadow-red-200">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-black text-base md:text-lg text-slate-900 tracking-wide">REDCODE</span>
                <span className="bg-slate-100 text-slate-700 text-[10px] px-1.5 py-0.5 rounded font-mono font-bold border border-slate-200">
                  HOSPITAL LAN
                </span>
              </div>
              <p className="text-[11px] text-slate-500 font-medium">Bệnh Viện Đa Khoa Thiện Hạnh</p>
            </div>
          </div>

          {/* Connection status badge */}
          <div className="flex items-center space-x-2">
            <div
              className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-bold border ${
                isConnected
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : 'bg-red-50 text-red-600 border-red-200 animate-pulse'
              }`}
            >
              <Radio className="w-3.5 h-3.5" />
              <span>{isConnected ? 'LAN CONNECTED' : 'OFFLINE'}</span>
            </div>

            {/* Audio Readiness quick toggle */}
            <button
              onClick={unlockAudio}
              title={audioReady ? 'Âm thanh đã sẵn sàng' : 'Chạm để bật quyền âm thanh'}
              className={`p-1.5 rounded-lg border text-xs flex items-center space-x-1 transition ${
                audioReady
                  ? 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
                  : 'bg-amber-50 text-amber-700 border-amber-300 animate-pulse'
              }`}
            >
              {audioReady ? <Volume2 className="w-4 h-4 text-emerald-600" /> : <VolumeX className="w-4 h-4 text-amber-600" />}
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        {user && (
          <nav className="flex items-center space-x-1 overflow-x-auto py-1 max-w-full">
            {allowedNav.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs md:text-sm font-semibold transition whitespace-nowrap ${
                    isActive
                      ? 'bg-slate-900 text-white shadow-sm'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        )}

        {/* User Info & Logout */}
        {user ? (
          <div className="flex items-center space-x-3 text-right">
            <div className="hidden sm:block">
              <div className="text-xs md:text-sm font-bold text-slate-800">{user.display_name}</div>
              <div className="text-[11px] text-slate-500 font-mono">
                {user.department?.name || 'Toàn viện'} •{' '}
                <span className="text-red-600 font-bold">{user.role}</span>
              </div>
            </div>
            <button
              onClick={logout}
              title="Đăng xuất"
              className="p-2 text-slate-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <Link
            to="/login"
            className="px-3.5 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-bold transition shadow-sm"
          >
            Đăng nhập
          </Link>
        )}
      </div>
    </header>
  );
}
