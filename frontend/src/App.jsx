import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { WebSocketProvider } from './context/WebSocketContext';
import Navigation from './components/Navigation';
import AlarmOverlay from './components/AlarmOverlay';
import Login from './pages/Login';
import OperatorDashboard from './pages/OperatorDashboard';
import ReceiverStationView from './pages/ReceiverStationView';
import AdminDashboard from './pages/AdminDashboard';
import ReportsView from './pages/ReportsView';

function ProtectedRoute({ children, requiredRole }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400 font-mono text-sm">
        Đang khởi động kết nối hệ thống...
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (requiredRole && user.role !== requiredRole && user.role !== 'ADMIN') {
    return <Navigate to="/" replace />;
  }

  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <WebSocketProvider>
        <div className="min-h-screen bg-slate-950 flex flex-col font-sans">
          {/* Fullscreen Alarm Overlay (Always present when alarm fires) */}
          <AlarmOverlay />

          {/* Navigation Bar */}
          <Navigation />

          {/* Main App Routes */}
          <main className="flex-1">
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route
                path="/"
                element={
                  <ProtectedRoute>
                    <OperatorDashboard />
                  </ProtectedRoute>
                }
              />
              {/* Kiosk view: accessible both as standalone kiosk screen or logged in */}
              <Route path="/kiosk" element={<ReceiverStationView />} />
              <Route
                path="/admin"
                element={
                  <ProtectedRoute requiredRole="ADMIN">
                    <AdminDashboard />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/reports"
                element={
                  <ProtectedRoute requiredRole="ADMIN">
                    <ReportsView />
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </WebSocketProvider>
    </AuthProvider>
  );
}
