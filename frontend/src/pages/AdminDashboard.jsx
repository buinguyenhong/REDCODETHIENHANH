import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';
import {
  Activity,
  Server,
  Database,
  Radio,
  Share2,
  Users,
  Building,
  Volume2,
  BellRing,
  Layers,
  History,
  CheckCircle,
  AlertTriangle,
  Play,
  RefreshCw,
  Plus,
  Edit2,
  Trash2,
  X,
  Upload,
  Music,
} from 'lucide-react';

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState('monitor'); // monitor | alarmTypes | stations | receiverGroups | departments | users | audio | audit
  const [stations, setStations] = useState([]);
  const [health, setHealth] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [usersList, setUsersList] = useState([]);
  const [alarmTypes, setAlarmTypes] = useState([]);
  const [receiverGroups, setReceiverGroups] = useState([]);
  const [audioFiles, setAudioFiles] = useState([]);
  const [systemEvents, setSystemEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState(null);

  // Modal states
  const [modalType, setModalType] = useState(null); // 'alarmType' | 'station' | 'receiverGroup' | 'department' | 'user' | 'audioUpload'
  const [editItem, setEditItem] = useState(null);

  // Form states
  const [alarmTypeForm, setAlarmTypeForm] = useState({
    code: '',
    name: '',
    description: '',
    priority: 1,
    display_color: '#dc2626',
    receiver_group_id: '',
    audio_file_path: '',
    repeat_count: 4,
    repeat_interval_ms: 1200,
    allowed_department_ids: [],
    validity_seconds: 300,
  });

  const [stationForm, setStationForm] = useState({
    station_code: '',
    name: '',
    department_id: '',
    location: '',
    device_token: '',
    receiver_group_ids: [],
  });

  const [groupForm, setGroupForm] = useState({
    code: '',
    name: '',
    description: '',
    station_ids: [],
  });

  const [deptForm, setDeptForm] = useState({
    code: '',
    name: '',
  });

  const [userForm, setUserForm] = useState({
    username: '',
    password: '',
    display_name: '',
    department_id: '',
    role: 'OPERATOR',
  });

  const [uploadAudioForm, setUploadAudioForm] = useState({
    code: '',
    name: '',
    file: null,
  });
  const fileInputRef = useRef(null);

  useEffect(() => {
    loadAllData();
    const interval = setInterval(loadMonitorData, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadAllData = async () => {
    setLoading(true);
    await Promise.all([loadMonitorData(), loadConfigData(), loadAuditEvents()]);
    setLoading(false);
  };

  const loadMonitorData = async () => {
    try {
      const [stData, hData] = await Promise.all([
        api.getStations(),
        api.getHealth(),
      ]);
      setStations(stData);
      setHealth(hData);
    } catch (e) {
      console.error('Lỗi cập nhật giám sát:', e);
    }
  };

  const loadConfigData = async () => {
    try {
      const [dData, uData, atData, rgData, auData] = await Promise.all([
        api.getDepartments(),
        api.getUsers(),
        api.getAlarmTypes(),
        api.getReceiverGroups(),
        api.getAudioFiles(),
      ]);
      setDepartments(dData);
      setUsersList(uData);
      setAlarmTypes(atData);
      setReceiverGroups(rgData);
      setAudioFiles(auData);
    } catch (e) {
      console.error('Lỗi tải cấu hình:', e);
    }
  };

  const loadAuditEvents = async () => {
    try {
      const events = await api.getSystemEvents();
      setSystemEvents(events);
    } catch (e) {
      console.error('Lỗi tải sự kiện hệ thống:', e);
    }
  };

  const notify = (msg) => {
    setActionMsg(msg);
    setTimeout(() => setActionMsg(null), 3500);
  };

  const handleTestAudio = async (stationId, stationCode) => {
    try {
      await api.testStationAudio(stationId);
      notify(`Đã gửi lệnh kiểm tra âm thanh tới trạm ${stationCode}`);
    } catch (err) {
      alert(`Không thể gửi lệnh test tới ${stationCode}: ${err.message}`);
    }
  };

  // --- CRUD: ALARM TYPES ---
  const openAlarmTypeModal = (item = null) => {
    setEditItem(item);
    if (item) {
      setAlarmTypeForm({
        code: item.code,
        name: item.name,
        description: item.description || '',
        priority: item.priority || 1,
        display_color: item.display_color || '#dc2626',
        receiver_group_id: item.receiver_group?.id || item.receiver_group_id || '',
        audio_file_path: (item.audio_sequence || []).join('\n'),
        repeat_count: item.repeat_count || 4,
        repeat_interval_ms: item.repeat_interval_ms || 1200,
        allowed_department_ids: item.allowed_department_ids || [],
        validity_seconds: item.validity_seconds || 300,
      });
    } else {
      setAlarmTypeForm({
        code: '',
        name: '',
        description: '',
        priority: 1,
        display_color: '#dc2626',
        receiver_group_id: receiverGroups[0]?.id || '',
        audio_file_path: audioFiles[0]?.file_path || '',
        repeat_count: 4,
        repeat_interval_ms: 1200,
        allowed_department_ids: [],
        validity_seconds: 300,
      });
    }
    setModalType('alarmType');
  };

  const saveAlarmType = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        code: alarmTypeForm.code.trim().toUpperCase(),
        name: alarmTypeForm.name.trim(),
        description: alarmTypeForm.description.trim(),
        priority: parseInt(alarmTypeForm.priority, 10),
        display_color: alarmTypeForm.display_color,
        receiver_group_id: alarmTypeForm.receiver_group_id ? parseInt(alarmTypeForm.receiver_group_id, 10) : null,
        audio_sequence: alarmTypeForm.audio_file_path.split('\n').map(path => path.trim()).filter(Boolean),
        repeat_count: parseInt(alarmTypeForm.repeat_count, 10),
        repeat_interval_ms: parseInt(alarmTypeForm.repeat_interval_ms, 10),
        validity_seconds: Number(alarmTypeForm.validity_seconds),
        enabled: true,
        allowed_department_ids: alarmTypeForm.allowed_department_ids,
      };

      if (editItem) {
        await api.updateAlarmType(editItem.id, payload);
        notify(`Đã cập nhật mã báo động ${payload.code}`);
      } else {
        await api.createAlarmType(payload);
        notify(`Đã thêm mới mã báo động ${payload.code}`);
      }
      setModalType(null);
      loadConfigData();
    } catch (err) {
      alert('Lỗi lưu mã báo động: ' + err.message);
    }
  };

  const deleteAlarmType = async (id, code) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xóa mã báo động ${code}?`)) return;
    try {
      await api.deleteAlarmType(id);
      notify(`Đã xóa mã báo động ${code}`);
      loadConfigData();
    } catch (err) {
      alert('Lỗi xóa: ' + err.message);
    }
  };

  // --- CRUD: STATIONS ---
  const openStationModal = (item = null) => {
    setEditItem(item);
    if (item) {
      setStationForm({
        station_code: item.station_code,
        name: item.name,
        department_id: item.department_id || '',
        location: item.location || '',
        device_token: '',
        receiver_group_ids: item.receiver_groups ? item.receiver_groups.map((g) => g.id) : [],
      });
    } else {
      setStationForm({
        station_code: '',
        name: '',
        department_id: departments[0]?.id || '',
        location: '',
        device_token: '',
        receiver_group_ids: [],
      });
    }
    setModalType('station');
  };

  const saveStation = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        station_code: stationForm.station_code.trim().toUpperCase(),
        name: stationForm.name.trim(),
        department_id: stationForm.department_id ? parseInt(stationForm.department_id, 10) : null,
        location: stationForm.location.trim(),
        receiver_group_ids: stationForm.receiver_group_ids.map((id) => parseInt(id, 10)),
      };

      if (editItem) {
        await api.updateStation(editItem.id, payload);
        notify(`Đã cập nhật trạm nhận ${payload.station_code}`);
      } else {
        const res = await api.registerStation(payload);
        notify('Trạm đã tạo. Mở màn hình trạm nhận trên thiết bị và đăng nhập Admin để xác nhận.');
        notify(`Đã đăng ký trạm nhận mới ${payload.station_code}`);
      }
      setModalType(null);
      loadMonitorData();
    } catch (err) {
      alert('Lỗi lưu trạm: ' + err.message);
    }
  };

  const deleteStation = async (id, code) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xóa trạm nhận ${code}?`)) return;
    try {
      await api.deleteStation(id);
      notify(`Đã xóa trạm nhận ${code}`);
      loadMonitorData();
    } catch (err) {
      alert('Lỗi xóa trạm: ' + err.message);
    }
  };

  // --- CRUD: DEPARTMENTS ---
  const openDepartmentModal = (item = null) => {
    setEditItem(item);
    if (item) {
      setDeptForm({ code: item.code, name: item.name });
    } else {
      setDeptForm({ code: '', name: '' });
    }
    setModalType('department');
  };

  const saveDepartment = async (e) => {
    e.preventDefault();
    try {
      if (editItem) {
        await api.updateDepartment(editItem.id, { name: deptForm.name.trim() });
        notify(`Đã cập nhật khoa/phòng ${deptForm.name}`);
      } else {
        await api.createDepartment({
          code: deptForm.code.trim().toUpperCase(),
          name: deptForm.name.trim(),
          enabled: true,
        });
        notify(`Đã thêm khoa/phòng ${deptForm.name}`);
      }
      setModalType(null);
      loadConfigData();
    } catch (err) {
      alert('Lỗi lưu khoa/phòng: ' + err.message);
    }
  };

  const deleteDepartment = async (id, name) => {
    if (!window.confirm(`Xóa khoa/phòng "${name}"?`)) return;
    try {
      await api.deleteDepartment(id);
      notify(`Đã xóa khoa/phòng ${name}`);
      loadConfigData();
    } catch (err) {
      alert('Lỗi xóa khoa: ' + err.message);
    }
  };

  // --- CRUD: USERS ---
  const openUserModal = (item = null) => {
    setEditItem(item);
    if (item) {
      setUserForm({
        username: item.username,
        password: '',
        display_name: item.display_name,
        department_id: item.department_id || '',
        role: item.role,
      });
    } else {
      setUserForm({
        username: '',
        password: '',
        display_name: '',
        department_id: departments[0]?.id || '',
        role: 'OPERATOR',
      });
    }
    setModalType('user');
  };

  const saveUser = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        username: userForm.username.trim(),
        display_name: userForm.display_name.trim(),
        department_id: userForm.department_id ? parseInt(userForm.department_id, 10) : null,
        role: userForm.role,
        enabled: true,
      };
      if (userForm.password) payload.password = userForm.password;

      if (editItem) {
        await api.updateUser(editItem.id, payload);
        notify(`Đã cập nhật tài khoản ${payload.username}`);
      } else {
        if (!userForm.password) {
          alert('Vui lòng nhập mật khẩu cho tài khoản mới');
          return;
        }
        await api.createUser(payload);
        notify(`Đã tạo tài khoản ${payload.username}`);
      }
      setModalType(null);
      loadConfigData();
    } catch (err) {
      alert('Lỗi lưu tài khoản: ' + err.message);
    }
  };

  const deleteUser = async (id, username) => {
    if (!window.confirm(`Xóa tài khoản ${username}?`)) return;
    try {
      await api.deleteUser(id);
      notify(`Đã xóa tài khoản ${username}`);
      loadConfigData();
    } catch (err) {
      alert('Lỗi xóa: ' + err.message);
    }
  };

  // --- CRUD: RECEIVER GROUPS ---
  const openReceiverGroupModal = (item = null) => {
    setEditItem(item);
    if (item) {
      setGroupForm({
        code: item.code,
        name: item.name,
        description: item.description || '',
        station_ids: undefined,
      });
    } else {
      setGroupForm({
        code: '',
        name: '',
        description: '',
        station_ids: [],
      });
    }
    setModalType('receiverGroup');
  };

  const saveReceiverGroup = async (e) => {
    e.preventDefault();
    try {
      const payload = {
        code: groupForm.code.trim().toUpperCase(),
        name: groupForm.name.trim(),
        description: groupForm.description.trim(),
        station_ids: groupForm.station_ids?.map((id) => parseInt(id, 10)),
        enabled: true,
      };

      if (editItem) {
        await api.updateReceiverGroup(editItem.id, payload);
        notify(`Đã cập nhật nhóm nhận ${payload.code}`);
      } else {
        await api.createReceiverGroup(payload);
        notify(`Đã tạo nhóm nhận ${payload.code}`);
      }
      setModalType(null);
      loadConfigData();
    } catch (err) {
      alert('Lỗi lưu nhóm: ' + err.message);
    }
  };

  const deleteReceiverGroup = async (id, code) => {
    if (!window.confirm(`Xóa nhóm nhận ${code}?`)) return;
    try {
      await api.deleteReceiverGroup(id);
      notify(`Đã xóa nhóm nhận ${code}`);
      loadConfigData();
    } catch (err) {
      alert('Lỗi xóa: ' + err.message);
    }
  };

  // --- AUDIO UPLOAD ---
  const handleAudioUpload = async (e) => {
    e.preventDefault();
    if (!uploadAudioForm.file) {
      alert('Vui lòng chọn file âm thanh (.wav hoặc .mp3)');
      return;
    }
    try {
      const fd = new FormData();
      fd.append('code', uploadAudioForm.code.trim().toUpperCase());
      fd.append('name', uploadAudioForm.name.trim());
      fd.append('file', uploadAudioForm.file);

      const res = await api.uploadAudio(fd);
      notify(`Đã tải lên file âm thanh ${res.code}`);
      setModalType(null);
      setUploadAudioForm({ code: '', name: '', file: null });
      loadConfigData();
    } catch (err) {
      alert('Lỗi tải file âm thanh: ' + err.message);
    }
  };

  const deleteAudioFile = async (id, code) => {
    if (!window.confirm(`Vô hiệu hóa file âm thanh ${code}?`)) return;
    try {
      await api.deleteAudioFile(id);
      notify(`Đã vô hiệu hóa file âm thanh ${code}`);
      loadConfigData();
    } catch (err) {
      alert('Lỗi: ' + err.message);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 p-4 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Top Header */}
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-4 border-b border-slate-200">
          <div>
            <h1 className="text-2xl font-black uppercase text-slate-900 tracking-wide flex items-center space-x-3">
              <Server className="w-7 h-7 text-red-600" />
              <span>TRUNG TÂM QUẢN TRỊ & CẤU HÌNH HỆ THỐNG</span>
            </h1>
            <p className="text-xs text-slate-500 font-mono mt-1">
              Bệnh viện Đa khoa Thiện Hạnh • Quản lý trạm nhận, mã báo động, phân nhóm & âm thanh
            </p>
          </div>

          <button
            onClick={loadAllData}
            className="flex items-center space-x-2 px-4 py-2 bg-white hover:bg-slate-100 border border-slate-300 rounded-xl text-xs font-mono font-bold text-slate-700 transition shadow-sm"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            <span>LÀM MỚI</span>
          </button>
        </div>

        {actionMsg && (
          <div className="p-3.5 bg-emerald-50 border border-emerald-300 rounded-xl text-emerald-800 text-sm flex items-center space-x-2 shadow-sm">
            <CheckCircle className="w-5 h-5 shrink-0 text-emerald-600" />
            <span className="font-semibold">{actionMsg}</span>
          </div>
        )}

        {/* 1. Core Health Overview Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm">
            <div className="flex items-center justify-between text-slate-500 text-xs font-mono mb-1.5">
              <span>REDCODE CORE</span>
              <Activity className="w-4 h-4 text-emerald-600" />
            </div>
            <div className="text-xl font-black text-slate-900">{health?.status === 'ok' ? 'HOẠT ĐỘNG' : 'LỖI'}</div>
            <div className="text-xs text-emerald-700 font-mono mt-0.5">FastAPI Engine OK</div>
          </div>

          <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm">
            <div className="flex items-center justify-between text-slate-500 text-xs font-mono mb-1.5">
              <span>DATABASE</span>
              <Database className="w-4 h-4 text-blue-600" />
            </div>
            <div className="text-xl font-black text-slate-900">{health?.database === 'ok' ? 'KẾT NỐI OK' : 'MẤT KẾT NỐI'}</div>
            <div className="text-xs text-slate-500 font-mono mt-0.5">PostgreSQL database: redcode</div>
          </div>

          <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm">
            <div className="flex items-center justify-between text-slate-500 text-xs font-mono mb-1.5">
              <span>TRẠM ONLINE</span>
              <Radio className="w-4 h-4 text-amber-600" />
            </div>
            <div className="text-xl font-black text-slate-900">
              {health?.active_stations || 0} / {health?.total_stations || 0}
            </div>
            <div className="text-xs text-amber-700 font-mono mt-0.5">Thiết bị đang hoạt động</div>
          </div>

          <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm">
            <div className="flex items-center justify-between text-slate-500 text-xs font-mono mb-1.5">
              <span>N8N INTEGRATION</span>
              <Share2 className="w-4 h-4 text-purple-600" />
            </div>
            <div className="text-xl font-black text-slate-900 uppercase">{health?.n8n || 'DEGRADED'}</div>
            <div className="text-xs text-slate-500 font-mono mt-0.5">Non-blocking background</div>
          </div>
        </div>

        {/* 2. Navigation Tabs */}
        <div className="flex space-x-2 border-b border-slate-200 pb-2 overflow-x-auto">
          {[
            { id: 'monitor', label: 'GIÁM SÁT THIẾT BỊ', icon: Radio },
            { id: 'alarmTypes', label: 'MÃ BÁO ĐỘNG & ÂM THANH', icon: BellRing },
            { id: 'stations', label: 'CẤU HÌNH TRẠM NHẬN', icon: Server },
            { id: 'receiverGroups', label: 'NHÓM NHẬN TIN', icon: Layers },
            { id: 'departments', label: 'KHOA / PHÒNG', icon: Building },
            { id: 'users', label: 'TÀI KHOẢN', icon: Users },
            { id: 'audio', label: 'THƯ VIỆN ÂM THANH', icon: Music },
            { id: 'audit', label: 'NHẬT KÝ HỆ THỐNG', icon: History },
          ].map((tab) => {
            const Icon = tab.icon;
            const isCur = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center space-x-2 px-3.5 py-2 rounded-xl font-mono text-xs font-bold transition whitespace-nowrap ${
                  isCur
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'bg-white text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-slate-200'
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* TAB 1: DEVICE MONITOR */}
        {activeTab === 'monitor' && (
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
            <div className="p-4 bg-slate-50 border-b border-slate-200 flex justify-between items-center">
              <span className="text-xs font-mono font-bold uppercase text-slate-700">
                DANH SÁCH GIÁM SÁT TRẠM NHẬN ({stations.length} TRẠM)
              </span>
              <span className="text-xs font-mono text-slate-500">
                Chu kỳ heartbeat: 5 giây • Quá 15s tự động đánh dấu Offline
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse font-mono text-xs">
                <thead>
                  <tr className="bg-slate-100/70 text-slate-600 border-b border-slate-200">
                    <th className="py-3 px-4">MÃ TRẠM</th>
                    <th className="py-3 px-4">TÊN THIẾT BỊ</th>
                    <th className="py-3 px-4">KHOA / PHÒNG</th>
                    <th className="py-3 px-4">VỊ TRÍ</th>
                    <th className="py-3 px-4">ĐỊA CHỈ IP</th>
                    <th className="py-3 px-4">TRẠNG THÁI</th>
                    <th className="py-3 px-4">ÂM THANH</th>
                    <th className="py-3 px-4">LẦN CUỐI THẤY</th>
                    <th className="py-3 px-4 text-center">THAO TÁC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {stations.map((st) => {
                    const isOnline = st.status === 'ONLINE';
                    return (
                      <tr key={st.id} className="hover:bg-slate-50 transition">
                        <td className="py-3 px-4 font-bold text-slate-900">{st.station_code}</td>
                        <td className="py-3 px-4 text-slate-800 font-sans font-medium">{st.name}</td>
                        <td className="py-3 px-4 text-slate-600 font-sans">{st.department?.name || 'Toàn viện'}</td>
                        <td className="py-3 px-4 text-slate-500 font-sans">{st.location}</td>
                        <td className="py-3 px-4 text-slate-500">{st.ip_address || '—'}</td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center space-x-1.5 px-2.5 py-0.5 rounded-full font-bold text-[11px] ${
                              isOnline
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : 'bg-slate-100 text-slate-500'
                            }`}
                          >
                            <span className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`} />
                            <span>{isOnline ? 'ONLINE' : 'OFFLINE'}</span>
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                              st.audio_ready
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : 'bg-amber-50 text-amber-700 border border-amber-200'
                            }`}
                          >
                            {st.audio_ready ? 'AUDIO READY' : 'NOT READY'}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-slate-500">
                          {st.last_seen_at ? new Date(st.last_seen_at).toLocaleTimeString('vi-VN') : 'Chưa kết nối'}
                        </td>
                        <td className="py-3 px-4 text-center">
                          <button
                            onClick={() => handleTestAudio(st.id, st.station_code)}
                            className="px-2.5 py-1 bg-slate-100 hover:bg-red-50 text-slate-700 hover:text-red-600 rounded border border-slate-200 text-[11px] font-bold transition flex items-center space-x-1 mx-auto"
                            title="Kiểm tra âm thanh tại trạm này"
                          >
                            <Play className="w-3 h-3 text-red-600" />
                            <span>Test Loa</span>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 2: ALARM TYPES & SOUND MAPPING */}
        {activeTab === 'alarmTypes' && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
              <div>
                <h2 className="text-lg font-bold text-slate-900 uppercase">
                  DANH MỤC MÃ BÁO ĐỘNG (ALARM TYPES)
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Tùy chỉnh mã code, nội dung thông báo mặc định, nhóm nhận và gán file âm thanh còi hú
                </p>
              </div>
              <button
                onClick={() => openAlarmTypeModal()}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-mono font-bold transition shadow-sm"
              >
                <Plus className="w-4 h-4" />
                <span>THÊM MÃ BÁO ĐỘNG</span>
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {alarmTypes.map((at) => (
                <div key={at.id} className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                  <div className="flex items-center justify-between">
                    <span
                      className="px-3 py-1 rounded font-black text-xs font-mono text-white shadow-sm"
                      style={{ backgroundColor: at.display_color || '#dc2626' }}
                    >
                      {at.code}
                    </span>
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={() => openAlarmTypeModal(at)}
                        className="p-1.5 text-slate-600 hover:text-blue-600 hover:bg-white rounded-lg border border-slate-200"
                        title="Chỉnh sửa"
                      >
                        <Edit2 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => deleteAlarmType(at.id, at.code)}
                        className="p-1.5 text-slate-600 hover:text-red-600 hover:bg-white rounded-lg border border-slate-200"
                        title="Xóa"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  <div>
                    <h3 className="font-bold text-slate-900 text-base">{at.name}</h3>
                    <p className="text-xs text-slate-600 mt-1 font-medium italic">
                      "{at.description || 'Chưa có thông điệp mẫu'}"
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-200 text-xs font-mono text-slate-600">
                    <div>
                      <span className="text-slate-400 block text-[10px]">NHÓM NHẬN TIN:</span>
                      <span className="font-bold text-slate-800">
                        {at.receiver_group?.name || 'Tất cả các trạm'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">CÒI HÚ / ÂM THANH:</span>
                      <span className="font-bold text-red-600 truncate block">
                        {at.audio_sequence && at.audio_sequence.length > 0 ? at.audio_sequence[0] : 'Mặc định'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">SỐ LẦN LẶP:</span>
                      <span className="font-bold text-slate-800">{at.repeat_count || 3} lần ({at.repeat_interval_ms || 1200}ms)</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px]">MỨC ĐỘ ƯU TIÊN:</span>
                      <span className="font-bold text-slate-800">Mức {at.priority || 1}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 3: STATIONS CONFIGURATION */}
        {activeTab === 'stations' && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
              <div>
                <h2 className="text-lg font-bold text-slate-900 uppercase">
                  QUẢN LÝ DANH SÁCH TRẠM NHẬN (RECEIVER STATIONS)
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Thêm mới, cấu hình token bảo mật, gán khoa phòng và nhóm tiếp nhận cảnh báo
                </p>
              </div>
              <button
                onClick={() => openStationModal()}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-mono font-bold transition shadow-sm"
              >
                <Plus className="w-4 h-4" />
                <span>THÊM TRẠM MỚI</span>
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse font-mono text-xs">
                <thead>
                  <tr className="bg-slate-50 text-slate-600 border-b border-slate-200">
                    <th className="py-3 px-4">MÃ TRẠM</th>
                    <th className="py-3 px-4">TÊN TRẠM</th>
                    <th className="py-3 px-4">KHOA PHÒNG</th>
                    <th className="py-3 px-4">VỊ TRÍ</th>
                    <th className="py-3 px-4">NHÓM TIẾP NHẬN</th>
                    <th className="py-3 px-4 text-center">THAO TÁC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {stations.map((st) => (
                    <tr key={st.id} className="hover:bg-slate-50">
                      <td className="py-3 px-4 font-bold text-slate-900">{st.station_code}</td>
                      <td className="py-3 px-4 text-slate-800 font-sans font-medium">{st.name}</td>
                      <td className="py-3 px-4 text-slate-600 font-sans">{st.department?.name || 'Toàn viện'}</td>
                      <td className="py-3 px-4 text-slate-500 font-sans">{st.location}</td>
                      <td className="py-3 px-4 text-slate-700">
                        {st.receiver_groups && st.receiver_groups.length > 0
                          ? st.receiver_groups.map((g) => g.name).join(', ')
                          : 'Tất cả'}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <div className="flex items-center justify-center space-x-2">
                          <button
                            onClick={() => openStationModal(st)}
                            className="p-1.5 text-slate-600 hover:text-blue-600 hover:bg-slate-100 rounded border border-slate-200"
                            title="Sửa"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => deleteStation(st.id, st.station_code)}
                            className="p-1.5 text-slate-600 hover:text-red-600 hover:bg-slate-100 rounded border border-slate-200"
                            title="Xóa"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 4: RECEIVER GROUPS */}
        {activeTab === 'receiverGroups' && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
              <div>
                <h2 className="text-lg font-bold text-slate-900 uppercase">
                  NHÓM TRẠM NHẬN TIN (RECEIVER GROUPS)
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Phân chia nhóm thiết bị tiếp nhận cảnh báo (VD: Nhóm toàn viện, Đội cấp cứu khẩn cấp, Khối Ngoại...)
                </p>
              </div>
              <button
                onClick={() => openReceiverGroupModal()}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-mono font-bold transition shadow-sm"
              >
                <Plus className="w-4 h-4" />
                <span>THÊM NHÓM MỚI</span>
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {receiverGroups.map((rg) => (
                <div key={rg.id} className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-blue-700 text-sm">{rg.code}</span>
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={() => openReceiverGroupModal(rg)}
                        className="p-1.5 text-slate-600 hover:text-blue-600 hover:bg-white rounded border border-slate-200"
                      >
                        <Edit2 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => deleteReceiverGroup(rg.id, rg.code)}
                        className="p-1.5 text-slate-600 hover:text-red-600 hover:bg-white rounded border border-slate-200"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  <h3 className="font-bold text-slate-900 text-base">{rg.name}</h3>
                  <p className="text-xs text-slate-500">{rg.description || 'Không có mô tả'}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 5: DEPARTMENTS */}
        {activeTab === 'departments' && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
              <div>
                <h2 className="text-lg font-bold text-slate-900 uppercase">
                  DANH MỤC KHOA / PHÒNG BAN ({departments.length})
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Quản lý danh sách các khoa lâm sàng, cận lâm sàng và phòng ban chức năng
                </p>
              </div>
              <button
                onClick={() => openDepartmentModal()}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-mono font-bold transition shadow-sm"
              >
                <Plus className="w-4 h-4" />
                <span>THÊM KHOA / PHÒNG</span>
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {departments.map((d) => (
                <div key={d.id} className="p-3 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between">
                  <div>
                    <span className="font-mono text-xs font-bold text-red-600 block">{d.code}</span>
                    <span className="text-slate-800 text-sm font-semibold">{d.name}</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <button
                      onClick={() => openDepartmentModal(d)}
                      className="p-1.5 text-slate-500 hover:text-blue-600 hover:bg-white rounded"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => deleteDepartment(d.id, d.name)}
                      className="p-1.5 text-slate-500 hover:text-red-600 hover:bg-white rounded"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 6: USERS */}
        {activeTab === 'users' && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
              <div>
                <h2 className="text-lg font-bold text-slate-900 uppercase">
                  QUẢN LÝ TÀI KHOẢN NGƯỜI DÙNG ({usersList.length})
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Phân quyền Admin, Operator (Điều dưỡng/Bác sĩ) và Viewer (Giám sát)
                </p>
              </div>
              <button
                onClick={() => openUserModal()}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-mono font-bold transition shadow-sm"
              >
                <Plus className="w-4 h-4" />
                <span>THÊM TÀI KHOẢN</span>
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse font-mono text-xs">
                <thead>
                  <tr className="bg-slate-50 text-slate-600 border-b border-slate-200">
                    <th className="py-3 px-4">TÊN ĐĂNG NHẬP</th>
                    <th className="py-3 px-4">HỌ VÀ TÊN</th>
                    <th className="py-3 px-4">KHOA / PHÒNG</th>
                    <th className="py-3 px-4">VAI TRÒ</th>
                    <th className="py-3 px-4">ĐĂNG NHẬP GẦN NHẤT</th>
                    <th className="py-3 px-4 text-center">THAO TÁC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {usersList.map((u) => (
                    <tr key={u.id} className="hover:bg-slate-50">
                      <td className="py-3 px-4 font-bold text-slate-900">{u.username}</td>
                      <td className="py-3 px-4 text-slate-800 font-sans font-medium">{u.display_name}</td>
                      <td className="py-3 px-4 text-slate-600 font-sans">{u.department?.name || 'Toàn viện'}</td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                            u.role === 'ADMIN'
                              ? 'bg-red-50 text-red-700 border border-red-200'
                              : u.role === 'OPERATOR'
                              ? 'bg-amber-50 text-amber-700 border border-amber-200'
                              : 'bg-blue-50 text-blue-700 border border-blue-200'
                          }`}
                        >
                          {u.role}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-slate-500">
                        {u.last_login_at ? new Date(u.last_login_at).toLocaleString('vi-VN') : 'Chưa đăng nhập'}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <div className="flex items-center justify-center space-x-2">
                          <button
                            onClick={() => openUserModal(u)}
                            className="p-1.5 text-slate-600 hover:text-blue-600 hover:bg-slate-100 rounded border border-slate-200"
                            title="Sửa"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => deleteUser(u.id, u.username)}
                            className="p-1.5 text-slate-600 hover:text-red-600 hover:bg-slate-100 rounded border border-slate-200"
                            title="Xóa"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 7: AUDIO LIBRARY & UPLOAD */}
        {activeTab === 'audio' && (
          <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
              <div>
                <h2 className="text-lg font-bold text-slate-900 uppercase">
                  THƯ VIỆN FILE ÂM THANH CỤC BỘ (LOCAL AUDIO LIBRARY)
                </h2>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  Tải lên file âm thanh (.wav / .mp3) lưu trữ tại server nội bộ, dùng để gán cho các mã báo động
                </p>
              </div>
              <button
                onClick={() => setModalType('audioUpload')}
                className="flex items-center space-x-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-mono font-bold transition shadow-sm"
              >
                <Upload className="w-4 h-4" />
                <span>UPLOAD FILE ÂM THANH</span>
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {audioFiles.map((af) => (
                <div key={af.id} className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-mono font-bold text-slate-900 text-sm">{af.code}</span>
                      <span className="text-slate-500 text-xs block font-sans">{af.name}</span>
                    </div>
                    <button
                      onClick={() => deleteAudioFile(af.id, af.code)}
                      className="p-1.5 text-slate-500 hover:text-red-600 hover:bg-white rounded border border-slate-200"
                      title="Vô hiệu hóa"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="pt-2 border-t border-slate-200">
                    <span className="text-[10px] font-mono text-slate-400 block mb-1">ĐƯỜNG DẪN: {af.file_path}</span>
                    <audio controls src={af.file_path} className="w-full h-8" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 8: AUDIT SYSTEM EVENTS */}
        {activeTab === 'audit' && (
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
            <div className="p-4 bg-slate-50 border-b border-slate-200 flex justify-between items-center">
              <span className="text-xs font-mono font-bold uppercase text-slate-700">
                NHẬT KÝ HOẠT ĐỘNG & BẢO MẬT HỆ THỐNG (AUDIT LOG — LƯU TRỮ VĨNH VIỄN)
              </span>
              <button onClick={loadAuditEvents} className="text-xs font-mono text-red-600 hover:underline font-bold">
                Làm mới
              </button>
            </div>

            <div className="overflow-x-auto max-h-[600px]">
              <table className="w-full text-left border-collapse font-mono text-xs">
                <thead>
                  <tr className="bg-slate-100/70 text-slate-600 border-b border-slate-200">
                    <th className="py-2.5 px-4">THỜI GIAN</th>
                    <th className="py-2.5 px-4">LOẠI SỰ KIỆN</th>
                    <th className="py-2.5 px-4">MỨC ĐỘ</th>
                    <th className="py-2.5 px-4">NỘI DUNG CHI TIẾT</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {systemEvents.map((ev) => {
                    const isErr = ev.severity === 'ERROR' || ev.severity === 'WARNING';
                    return (
                      <tr key={ev.id} className="hover:bg-slate-50">
                        <td className="py-2 px-4 text-slate-500 whitespace-nowrap">
                          {new Date(ev.created_at).toLocaleString('vi-VN')}
                        </td>
                        <td className="py-2 px-4 font-bold text-slate-900">{ev.event_type}</td>
                        <td className="py-2 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              isErr
                                ? 'bg-red-50 text-red-700 border border-red-200'
                                : 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {ev.severity}
                          </span>
                        </td>
                        <td className="py-2 px-4 text-slate-700">{ev.message}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* ======================================================== */}
      {/* MODAL 1: ALARM TYPE EDIT/CREATE WITH SOUND MAPPING       */}
      {/* ======================================================== */}
      {modalType === 'alarmType' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 max-w-2xl w-full shadow-2xl space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-lg font-bold text-slate-900 uppercase">
                {editItem ? `CHỈNH SỬA MÃ BÁO ĐỘNG: ${editItem.code}` : 'THÊM MÃ BÁO ĐỘNG MỚI'}
              </h3>
              <button onClick={() => setModalType(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={saveAlarmType} className="space-y-4 text-xs font-mono">
              <label className="block">Thời gian hiệu lực cảnh báo (giây)<input type="number" min="10" max="86400" required className="w-full border p-2" value={alarmTypeForm.validity_seconds} onChange={event => setAlarmTypeForm({...alarmTypeForm, validity_seconds: event.target.value})} /></label>
              <label className="block">Chuỗi audio theo thứ tự (mỗi dòng một đường dẫn local)<textarea rows={4} className="w-full border p-2" value={alarmTypeForm.audio_file_path} onChange={event => setAlarmTypeForm({...alarmTypeForm, audio_file_path: event.target.value})} /></label>
              <fieldset className="border border-slate-300 p-3">
                <legend>Khoa/phòng được phép phát</legend>
                {departments.map(dept => <label key={dept.id} className="block py-1"><input type="checkbox" checked={alarmTypeForm.allowed_department_ids?.includes(dept.id) || false} onChange={event => setAlarmTypeForm({...alarmTypeForm, allowed_department_ids: event.target.checked ? [...(alarmTypeForm.allowed_department_ids || []), dept.id] : alarmTypeForm.allowed_department_ids.filter(id => id !== dept.id)})} /> {dept.name}</label>)}
              </fieldset>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Mã Code (Định danh):</label>
                  <input
                    type="text"
                    required
                    value={alarmTypeForm.code}
                    onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, code: e.target.value })}
                    placeholder="VD: RED_CODE_1"
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 focus:border-red-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Màu sắc nhận diện:</label>
                  <div className="flex items-center space-x-2">
                    <input
                      type="color"
                      value={alarmTypeForm.display_color}
                      onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, display_color: e.target.value })}
                      className="w-10 h-10 border border-slate-300 rounded cursor-pointer"
                    />
                    <input
                      type="text"
                      value={alarmTypeForm.display_color}
                      onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, display_color: e.target.value })}
                      className="flex-1 bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Tên Tiêu Đề Báo Động:</label>
                <input
                  type="text"
                  required
                  value={alarmTypeForm.name}
                  onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, name: e.target.value })}
                  placeholder="VD: RED CODE 1 — Ngừng Tuần Hoàn Hô Hấp"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 text-sm font-sans focus:border-red-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">
                  Nội dung thông báo mẫu / Mô tả chi tiết:
                </label>
                <textarea
                  rows={2}
                  value={alarmTypeForm.description}
                  onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, description: e.target.value })}
                  placeholder="VD: Cấp cứu ngừng hô hấp tuần hoàn khẩn cấp tại phòng điều trị"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 text-sm font-sans focus:border-red-500 focus:outline-none"
                />
              </div>

              {/* Sound Mapping */}
              <div className="bg-red-50/50 border border-red-100 p-4 rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-red-900 uppercase flex items-center space-x-2">
                    <Volume2 className="w-4 h-4 text-red-600" />
                    <span>GÁN FILE ÂM THANH CÒI HÚ (SOUND MAPPING):</span>
                  </span>
                </div>
                <div>
                  <select
                    value={alarmTypeForm.audio_file_path}
                    onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, audio_file_path: e.target.value })}
                    className="w-full bg-white border border-slate-300 rounded-lg p-2.5 text-slate-900 font-mono focus:border-red-500 focus:outline-none"
                  >
                    <option value="">-- Không phát âm thanh --</option>
                    {audioFiles.map((af) => (
                      <option key={af.id} value={af.file_path}>
                        {af.code} — {af.name} ({af.file_path})
                      </option>
                    ))}
                  </select>
                </div>
                {alarmTypeForm.audio_file_path && (
                  <audio controls src={alarmTypeForm.audio_file_path} className="w-full h-8 mt-1" />
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Nhóm nhận tin:</label>
                  <select
                    value={alarmTypeForm.receiver_group_id}
                    onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, receiver_group_id: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  >
                    <option value="">Toàn bệnh viện (All)</option>
                    {receiverGroups.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Số lần lặp còi:</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={alarmTypeForm.repeat_count}
                    onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, repeat_count: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  />
                </div>

                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Khoảng cách lặp (ms):</label>
                  <input
                    type="number"
                    step="100"
                    min="500"
                    value={alarmTypeForm.repeat_interval_ms}
                    onChange={(e) => setAlarmTypeForm({ ...alarmTypeForm, repeat_interval_ms: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  />
                </div>
              </div>

              <div className="flex space-x-3 pt-3 border-t border-slate-100">
                <button
                  type="submit"
                  className="flex-1 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-sm transition shadow-sm"
                >
                  LƯU MÃ BÁO ĐỘNG
                </button>
                <button
                  type="button"
                  onClick={() => setModalType(null)}
                  className="px-5 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl text-sm transition"
                >
                  HỦY
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL 2: STATION CREATE/EDIT                             */}
      {/* ======================================================== */}
      {modalType === 'station' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 max-w-lg w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-lg font-bold text-slate-900 uppercase">
                {editItem ? `SỬA TRẠM: ${editItem.station_code}` : 'THÊM TRẠM NHẬN MỚI'}
              </h3>
              <button onClick={() => setModalType(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={saveStation} className="space-y-4 text-xs font-mono">
              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Mã trạm (VD: ST-CC-02):</label>
                <input
                  type="text"
                  required
                  value={stationForm.station_code}
                  onChange={(e) => setStationForm({ ...stationForm, station_code: e.target.value })}
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Tên thiết bị trạm:</label>
                <input
                  type="text"
                  required
                  value={stationForm.name}
                  onChange={(e) => setStationForm({ ...stationForm, name: e.target.value })}
                  placeholder="VD: Kiosk Cấp Cứu 02"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 font-sans"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Khoa / Phòng:</label>
                  <select
                    value={stationForm.department_id}
                    onChange={(e) => setStationForm({ ...stationForm, department_id: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  >
                    <option value="">Toàn viện</option>
                    {departments.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Vị trí lắp đặt:</label>
                  <input
                    type="text"
                    value={stationForm.location}
                    onChange={(e) => setStationForm({ ...stationForm, location: e.target.value })}
                    placeholder="VD: Sảnh tiếp nhận Tầng 1"
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 font-sans"
                  />
                </div>
              </div>

              <p>Trên thiết bị nhận, Admin chọn trạm và bấm “Xác nhận thiết bị này”. Không cần nhập mã bảo mật thủ công.</p>

              <div className="flex space-x-3 pt-3 border-t border-slate-100">
                <button
                  type="submit"
                  className="flex-1 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-sm transition shadow-sm"
                >
                  LƯU TRẠM NHẬN
                </button>
                <button
                  type="button"
                  onClick={() => setModalType(null)}
                  className="px-5 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl text-sm transition"
                >
                  HỦY
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL 3: DEPARTMENT CREATE/EDIT                          */}
      {/* ======================================================== */}
      {modalType === 'department' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-lg font-bold text-slate-900 uppercase">
                {editItem ? `SỬA KHOA: ${editItem.code}` : 'THÊM KHOA / PHÒNG'}
              </h3>
              <button onClick={() => setModalType(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={saveDepartment} className="space-y-4 text-xs font-mono">
              {!editItem && (
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Mã khoa (VD: CC, GMHS):</label>
                  <input
                    type="text"
                    required
                    value={deptForm.code}
                    onChange={(e) => setDeptForm({ ...deptForm, code: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  />
                </div>
              )}
              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Tên khoa / phòng:</label>
                <input
                  type="text"
                  required
                  value={deptForm.name}
                  onChange={(e) => setDeptForm({ ...deptForm, name: e.target.value })}
                  placeholder="VD: Khoa Cấp Cứu"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 font-sans"
                />
              </div>

              <div className="flex space-x-3 pt-3 border-t border-slate-100">
                <button
                  type="submit"
                  className="flex-1 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-sm transition shadow-sm"
                >
                  LƯU
                </button>
                <button
                  type="button"
                  onClick={() => setModalType(null)}
                  className="px-5 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl text-sm transition"
                >
                  HỦY
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL 4: USER CREATE/EDIT                                */}
      {/* ======================================================== */}
      {modalType === 'user' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-lg font-bold text-slate-900 uppercase">
                {editItem ? `SỬA TÀI KHOẢN: ${editItem.username}` : 'THÊM TÀI KHOẢN MỚI'}
              </h3>
              <button onClick={() => setModalType(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={saveUser} className="space-y-4 text-xs font-mono">
              {!editItem && (
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Tên đăng nhập:</label>
                  <input
                    type="text"
                    required
                    value={userForm.username}
                    onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  />
                </div>
              )}

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">
                  Mật khẩu {editItem && '(để trống nếu không đổi)'}:
                </label>
                <input
                  type="password"
                  value={userForm.password}
                  onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Họ và tên / Hiển thị:</label>
                <input
                  type="text"
                  required
                  value={userForm.display_name}
                  onChange={(e) => setUserForm({ ...userForm, display_name: e.target.value })}
                  placeholder="VD: BS. Nguyễn Văn A"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 font-sans"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Khoa / Phòng:</label>
                  <select
                    value={userForm.department_id}
                    onChange={(e) => setUserForm({ ...userForm, department_id: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  >
                    <option value="">Toàn viện</option>
                    {departments.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Vai trò:</label>
                  <select
                    value={userForm.role}
                    onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  >
                    <option value="OPERATOR">OPERATOR (Phát/Xử lý)</option>
                    <option value="ADMIN">ADMIN (Quản trị)</option>
                  </select>
                </div>
              </div>

              <div className="flex space-x-3 pt-3 border-t border-slate-100">
                <button
                  type="submit"
                  className="flex-1 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-sm transition shadow-sm"
                >
                  LƯU TÀI KHOẢN
                </button>
                <button
                  type="button"
                  onClick={() => setModalType(null)}
                  className="px-5 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl text-sm transition"
                >
                  HỦY
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL 5: RECEIVER GROUP CREATE/EDIT                      */}
      {/* ======================================================== */}
      {modalType === 'receiverGroup' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-lg font-bold text-slate-900 uppercase">
                {editItem ? `SỬA NHÓM: ${editItem.code}` : 'THÊM NHÓM NHẬN MỚI'}
              </h3>
              <button onClick={() => setModalType(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={saveReceiverGroup} className="space-y-4 text-xs font-mono">
              {!editItem && (
                <div>
                  <label className="block text-slate-600 font-bold uppercase mb-1">Mã nhóm (VD: EMERGENCY_TEAM):</label>
                  <input
                    type="text"
                    required
                    value={groupForm.code}
                    onChange={(e) => setGroupForm({ ...groupForm, code: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                  />
                </div>
              )}

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Tên nhóm:</label>
                <input
                  type="text"
                  required
                  value={groupForm.name}
                  onChange={(e) => setGroupForm({ ...groupForm, name: e.target.value })}
                  placeholder="VD: Đội Phản Ứng Nhanh"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 font-sans"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Mô tả nhóm:</label>
                <input
                  type="text"
                  value={groupForm.description}
                  onChange={(e) => setGroupForm({ ...groupForm, description: e.target.value })}
                  placeholder="VD: Trực tiếp nhận báo động Redcode 1 và 2"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 font-sans"
                />
              </div>

              <div className="flex space-x-3 pt-3 border-t border-slate-100">
                <button
                  type="submit"
                  className="flex-1 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-sm transition shadow-sm"
                >
                  LƯU NHÓM
                </button>
                <button
                  type="button"
                  onClick={() => setModalType(null)}
                  className="px-5 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl text-sm transition"
                >
                  HỦY
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL 6: AUDIO FILE UPLOAD                               */}
      {/* ======================================================== */}
      {modalType === 'audioUpload' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <h3 className="text-lg font-bold text-slate-900 uppercase">UPLOAD FILE ÂM THANH MỚI</h3>
              <button onClick={() => setModalType(null)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleAudioUpload} className="space-y-4 text-xs font-mono">
              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Mã file (VD: AUDIO_RC3):</label>
                <input
                  type="text"
                  required
                  value={uploadAudioForm.code}
                  onChange={(e) => setUploadAudioForm({ ...uploadAudioForm, code: e.target.value })}
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Tên mô tả âm thanh:</label>
                <input
                  type="text"
                  required
                  value={uploadAudioForm.name}
                  onChange={(e) => setUploadAudioForm({ ...uploadAudioForm, name: e.target.value })}
                  placeholder="VD: Còi báo động ngừng tim khoa Nhi"
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-slate-900 font-sans"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold uppercase mb-1">Chọn file (.wav / .mp3):</label>
                <input
                  type="file"
                  required
                  accept="audio/wav,audio/mp3,audio/mpeg"
                  onChange={(e) => setUploadAudioForm({ ...uploadAudioForm, file: e.target.files[0] })}
                  className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2 text-slate-900"
                />
              </div>

              <div className="flex space-x-3 pt-3 border-t border-slate-100">
                <button
                  type="submit"
                  className="flex-1 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-sm transition shadow-sm"
                >
                  TẢI LÊN SERVER
                </button>
                <button
                  type="button"
                  onClick={() => setModalType(null)}
                  className="px-5 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl text-sm transition"
                >
                  HỦY
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
