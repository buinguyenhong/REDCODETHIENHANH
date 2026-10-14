import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

// Bài kiểm thử này không kiểm tra hành vi chạy, nó kiểm tra một loại lỗi mà cả
// ``npm run build`` lẫn bộ test hành vi đều mù: một khối JSX bị render hai lần
// do hai lần sửa có neo khác nhau. Lỗi đó đã xảy ra thật ở AdminDashboard.jsx
// (fieldset "Nhóm nhận tin của trạm" xuất hiện hai lần) và chỉ lộ ra khi đọc mã.
//
// Cách bắt: mỗi file .jsx không được có hai ``<legend>`` mang cùng nội dung
// hiển thị trong cùng một file. Hai nhãn giống nhau trong một trang là gần như
// luôn là lỗi sao chép, vì người dùng không phân biệt được khối nào là khối nào.

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, '..', 'src');

function collectJsxFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      out.push(...collectJsxFiles(full));
    } else if (name.endsWith('.jsx') || name.endsWith('.js')) {
      out.push(full);
    }
  }
  return out;
}

// Rút phần chữ người dùng nhìn thấy của một thẻ JSX: bỏ mọi biểu thức {…} và
// mọi thẻ con, gộp khoảng trắng. ``<legend ...>Nhóm nhận tin của trạm</legend>``
// và ``<legend className="x">Nhóm nhận tin của trạm</legend>`` cho cùng kết quả.
function visibleText(inner) {
  const withoutExpressions = inner.replace(/\{[\s\S]*?\}/g, ' ');
  const withoutTags = withoutExpressions.replace(/<[^>]*>/g, ' ');
  return withoutTags.replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
}

function extractLegends(source) {
  const found = [];
  const re = /<legend\b[^>]*>([\s\S]*?)<\/legend>/g;
  let m;
  while ((m = re.exec(source)) !== null) {
    const text = visibleText(m[1]);
    if (text) found.push(text);
  }
  return found;
}

test('không file JSX nào render hai legend cùng nội dung', () => {
  const offenders = [];
  for (const file of collectJsxFiles(srcRoot)) {
    const source = readFileSync(file, 'utf8');
    const seen = new Map();
    for (const text of extractLegends(source)) {
      seen.set(text, (seen.get(text) || 0) + 1);
    }
    for (const [text, count] of seen) {
      if (count > 1) {
        offenders.push(`${relative(srcRoot, file)}: "${text}" xuất hiện ${count} lần`);
      }
    }
  }
  assert.deepEqual(offenders, [], `legend bị lặp:\n${offenders.join('\n')}`);
});

test('bộ dò legend thật sự nhìn thấy các legend đang có', () => {
  // Chống trường hợp regex hỏng rồi bài test trên xanh một cách vô nghĩa.
  const source = readFileSync(join(srcRoot, 'pages', 'AdminDashboard.jsx'), 'utf8');
  const legends = extractLegends(source);
  assert.ok(
    legends.includes('Nhóm nhận tin của trạm'),
    `không tìm thấy legend "Nhóm nhận tin của trạm", chỉ thấy: ${JSON.stringify(legends)}`
  );
});

test('bộ dò legend bắt được một legend bị nhân đôi cố ý', () => {
  const duplicated = `
    <fieldset><legend className="a">Nhóm nhận tin của trạm</legend></fieldset>
    <fieldset><legend className="b">Nhóm nhận tin của trạm</legend></fieldset>
  `;
  const seen = new Map();
  for (const text of extractLegends(duplicated)) {
    seen.set(text, (seen.get(text) || 0) + 1);
  }
  assert.equal(seen.get('Nhóm nhận tin của trạm'), 2);
});
