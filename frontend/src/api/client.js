const API_BASE = '/api';

export async function apiRequest(endpoint, options = {}) {
  const token = localStorage.getItem('redcode_token');
  const headers = {
    ...options.headers,
  };

  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
    signal: options.signal || AbortSignal.timeout(15000),
  });

  if (response.status === 401 && !endpoint.includes('/auth/login') && !endpoint.startsWith('/stations')) {
    localStorage.removeItem('redcode_token');
    localStorage.removeItem('redcode_user');
    window.location.href = '/login';
    throw new Error('Phiên đăng nhập đã hết hạn');
  }

  if (!response.ok) {
    let errorDetail = 'Lỗi hệ thống';
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errJson.message || errorDetail;
    } catch (_) {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(errorDetail);
  }

  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  // Auth
  login: (username, password) =>
    apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  getMe: () => apiRequest('/auth/me'),
  logout: () => apiRequest('/auth/logout', { method: 'POST' }),

  // Departments
  getDepartments: (enabledOnly = false) =>
    apiRequest(`/departments${enabledOnly ? '?enabled_only=true' : ''}`),
  createDepartment: (data) =>
    apiRequest('/departments', { method: 'POST', body: JSON.stringify(data) }),
  updateDepartment: (id, data) =>
    apiRequest(`/departments/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Users
  getUsers: (deptId) =>
    apiRequest(`/users${deptId ? `?department_id=${deptId}` : ''}`),
  createUser: (data) =>
    apiRequest('/users', { method: 'POST', body: JSON.stringify(data) }),
  updateUser: (id, data) =>
    apiRequest(`/users/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Stations
  activateStation: (data) => apiRequest('/stations/activate', { method: 'POST', body: JSON.stringify(data) }),
  getStations: (statusFilter) =>
    apiRequest(`/stations${statusFilter ? `?status_filter=${statusFilter}` : ''}`),
  getStation: (id) => apiRequest(`/stations/${id}`),
  getStationActiveAlarms: (stationCode, token) =>
    apiRequest(`/stations/${stationCode}/active-alarms`, {
      headers: token ? { 'X-Station-Token': token } : {},
    }),
  registerStation: (data) =>
    apiRequest('/stations/register', { method: 'POST', body: JSON.stringify(data) }),
  stationHeartbeat: (data) =>
    apiRequest('/stations/heartbeat', { method: 'POST', body: JSON.stringify(data) }),
  dismissStationAlarm: (data) =>
    apiRequest('/stations/dismiss', { method: 'POST', body: JSON.stringify(data) }),
  testStationAudio: (id) =>
    apiRequest(`/stations/${id}/audio-test`, { method: 'POST' }),

  // Alarm Types
  getAlarmTypes: (enabledOnly = false) =>
    apiRequest(`/alarm-types${enabledOnly ? '?enabled_only=true' : ''}`),
  getPermittedAlarmTypes: () => apiRequest('/alarm-types?enabled_only=true&permitted_only=true'),
  createAlarmType: (data) =>
    apiRequest('/alarm-types', { method: 'POST', body: JSON.stringify(data) }),
  updateAlarmType: (id, data) =>
    apiRequest(`/alarm-types/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Receiver Groups
  getReceiverGroups: (enabledOnly = false) =>
    apiRequest(`/receiver-groups${enabledOnly ? '?enabled_only=true' : ''}`),
  createReceiverGroup: (data) =>
    apiRequest('/receiver-groups', { method: 'POST', body: JSON.stringify(data) }),
  updateReceiverGroup: (id, data) =>
    apiRequest(`/receiver-groups/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Alarms
  getAlarms: (statusFilter, limit = 50, offset = 0) =>
    apiRequest(`/alarms?limit=${limit}&offset=${offset}${statusFilter ? `&status_filter=${statusFilter}` : ''}`),
  getAlarm: (id) => apiRequest(`/alarms/${id}`),
  createAlarm: (data) =>
    apiRequest('/alarms', { method: 'POST', body: JSON.stringify(data) }),
  cancelAlarm: (id) =>
    apiRequest(`/alarms/${id}/cancel`, { method: 'POST' }),

  // Reports
  getReportsSummary: (from, to) => {
    const params = new URLSearchParams();
    if (from) params.append('from_date', from);
    if (to) params.append('to_date', to);
    return apiRequest(`/reports/summary?${params.toString()}`);
  },
  exportXlsxUrl: (from, to) => {
    const params = new URLSearchParams();
    if (from) params.append('from_date', from);
    if (to) params.append('to_date', to);
    return `/api/reports/export-xlsx?${params.toString()}`;
  },

  // Audio
  getAudioFiles: () => apiRequest('/audio'),
  uploadAudio: (formData) =>
    apiRequest('/audio/upload', {
      method: 'POST',
      body: formData,
    }),
  deleteAudioFile: (id) => apiRequest(`/audio/${id}`, { method: 'DELETE' }),

  // Deletions & updates
  deleteDepartment: (id) => apiRequest(`/departments/${id}`, { method: 'DELETE' }),
  deleteUser: (id) => apiRequest(`/users/${id}`, { method: 'DELETE' }),
  deleteStation: (id) => apiRequest(`/stations/${id}`, { method: 'DELETE' }),
  updateStation: (id, data) => apiRequest(`/stations/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteAlarmType: (id) => apiRequest(`/alarm-types/${id}`, { method: 'DELETE' }),
  deleteReceiverGroup: (id) => apiRequest(`/receiver-groups/${id}`, { method: 'DELETE' }),

  // System & Health
  getSystemStatus: () => apiRequest('/system/status'),
  getSystemEvents: (type, severity, limit = 100) => {
    const params = new URLSearchParams({ limit });
    if (type) params.append('event_type', type);
    if (severity) params.append('severity', severity);
    return apiRequest(`/system/events?${params.toString()}`);
  },
  getHealth: () => apiRequest('/health'),
  getHealthDb: () => apiRequest('/health/db'),
  getHealthWebsocket: () => apiRequest('/health/websocket'),
};
