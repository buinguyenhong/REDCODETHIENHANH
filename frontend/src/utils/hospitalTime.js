/**
 * Định dạng ngày YYYY-MM-DD theo múi giờ bệnh viện (Asia/Ho_Chi_Minh).
 *
 * ``toISOString().split('T')[0]`` lấy theo giờ UTC, nên trong ca trực đêm từ
 * 00:00 đến 06:59 sáng giờ Việt Nam, ngày mặc định bị lùi về hôm qua và làm ẩn
 * toàn bộ báo động vừa phát trong đêm.
 */
export function formatHospitalDate(date = new Date()) {
  const d = date instanceof Date ? date : new Date(date);
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(d);
}

