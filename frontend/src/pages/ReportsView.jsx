import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { BarChart3, Calendar, FileSpreadsheet } from 'lucide-react';

export default function ReportsView() {
  const [fromDate, setFromDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d.toISOString().split('T')[0];
  });
  const [toDate, setToDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    loadSummary();
  }, [fromDate, toDate]);

  const loadSummary = async () => {
    setLoading(true);
    try {
      const data = await api.getReportsSummary(fromDate, toDate);
      setSummary(data);
    } catch (e) {
      console.error('Lỗi tải báo cáo tổng hợp:', e);
    } finally {
      setLoading(false);
    }
  };

  const handleExportXlsx = async () => {
    setExporting(true);
    try {
      const token = localStorage.getItem('redcode_token');
      const url = api.exportXlsxUrl(fromDate, toDate);
      const res = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) throw new Error('Không thể xuất file');
      const blob = await res.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = `baocao_redcode_${fromDate}_den_${toDate}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      alert('Lỗi xuất file Excel: ' + err.message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 p-4 md:p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-4 border-b border-slate-200">
          <div>
            <h1 className="text-2xl font-black uppercase text-slate-900 tracking-wide flex items-center space-x-3">
              <BarChart3 className="w-7 h-7 text-red-600" />
              <span>BÁO CÁO & THỐNG KÊ REDCODE</span>
            </h1>
            <p className="text-xs text-slate-500 font-mono mt-1">
              Dữ liệu lưu trữ bất biến phục vụ kiểm chuẩn và đối chiếu bệnh viện
            </p>
          </div>

          <button
            onClick={handleExportXlsx}
            disabled={exporting}
            className="flex items-center space-x-2 px-5 py-3 bg-emerald-600 hover:bg-emerald-700 active:scale-95 text-white font-bold rounded-xl shadow-md transition text-sm disabled:opacity-50"
          >
            <FileSpreadsheet className="w-5 h-5" />
            <span>{exporting ? 'ĐANG TẠO FILE...' : 'XUẤT BÁO CÁO EXCEL (.XLSX)'}</span>
          </button>
        </div>

        {/* Date Filter Bar */}
        <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm flex flex-col sm:flex-row items-center gap-4">
          <div className="flex items-center space-x-2 text-xs font-mono text-slate-600 uppercase">
            <Calendar className="w-4 h-4 text-slate-400" />
            <span>Khoảng thời gian:</span>
          </div>

          <div className="flex items-center space-x-3 w-full sm:w-auto">
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="bg-slate-50 border border-slate-300 text-slate-800 rounded-lg px-3 py-1.5 text-sm font-mono focus:border-red-500 focus:outline-none"
            />
            <span className="text-slate-400 text-xs uppercase font-mono">Đến</span>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="bg-slate-50 border border-slate-300 text-slate-800 rounded-lg px-3 py-1.5 text-sm font-mono focus:border-red-500 focus:outline-none"
            />
          </div>

          <button
            onClick={loadSummary}
            className="px-4 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-mono text-xs font-bold rounded-lg border border-slate-200 transition"
          >
            Lọc dữ liệu
          </button>
        </div>

        {/* Summary Metric Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-sm">
            <span className="text-xs font-mono text-slate-500 uppercase block mb-1">TỔNG SỐ LƯỢT BÁO ĐỘNG</span>
            <div className="text-3xl font-black text-slate-900">{summary?.total_alarms || 0}</div>
            <span className="text-xs text-slate-400 font-mono mt-1 block">Trong kỳ lọc đã chọn</span>
          </div>

          <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-sm">
            <span className="text-xs font-mono text-slate-500 uppercase block mb-1">CẢNH BÁO ĐANG HOẠT ĐỘNG</span>
            <div className="text-3xl font-black text-red-600">
              {summary?.by_status?.ACTIVE || 0}
            </div>
            <span className="text-xs text-red-600/80 font-mono mt-1 block">Đang trong thời hạn hiệu lực</span>
          </div>

          <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-sm">
            <span className="text-xs font-mono text-slate-500 uppercase block mb-1">SỰ CỐ TRẠM OFFLINE</span>
            <div className="text-3xl font-black text-amber-600">
              {summary?.device_offline_events_count || 0}
            </div>
            <span className="text-xs text-slate-400 font-mono mt-1 block">Số lần ngắt kết nối mạng</span>
          </div>
        </div>

        {/* Breakdown by Alarm Type & Department */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* By Type */}
          <div className="bg-white border border-slate-200 p-6 rounded-2xl shadow-sm">
            <h2 className="text-sm font-mono font-bold uppercase text-slate-900 mb-4 pb-2 border-b border-slate-100">
              PHÂN BỐ THEO MÃ BÁO ĐỘNG
            </h2>
            <div className="space-y-3">
              {summary?.by_type && Object.keys(summary.by_type).length > 0 ? (
                Object.entries(summary.by_type).map(([name, count]) => (
                  <div key={name} className="flex justify-between items-center p-3 bg-slate-50 rounded-lg text-sm border border-slate-200">
                    <span className="font-bold text-slate-800">{name}</span>
                    <span className="font-mono font-bold text-red-600 text-base">{count} lượt</span>
                  </div>
                ))
              ) : (
                <p className="text-slate-400 text-xs font-mono py-8 text-center">Chưa có dữ liệu</p>
              )}
            </div>
          </div>

          {/* By Department */}
          <div className="bg-white border border-slate-200 p-6 rounded-2xl shadow-sm">
            <h2 className="text-sm font-mono font-bold uppercase text-slate-900 mb-4 pb-2 border-b border-slate-100">
              PHÂN BỐ THEO KHOA / PHÒNG PHÁT TÍN HIỆU
            </h2>
            <div className="space-y-3">
              {summary?.by_department && Object.keys(summary.by_department).length > 0 ? (
                Object.entries(summary.by_department).map(([name, count]) => (
                  <div key={name} className="flex justify-between items-center p-3 bg-slate-50 rounded-lg text-sm border border-slate-200">
                    <span className="font-bold text-slate-800">{name}</span>
                    <span className="font-mono font-bold text-blue-600 text-base">{count} lượt</span>
                  </div>
                ))
              ) : (
                <p className="text-slate-400 text-xs font-mono py-8 text-center">Chưa có dữ liệu</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
