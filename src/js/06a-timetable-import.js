/* 图片只发送给本机 API；识别为草稿，确认前不写入课程或设置。 */
const TT_DRAFT = { rows: [], image: '', warnings: [], rawText: '', busy: false, error: '' };

function termMonday(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '';
  const d = parseD(value + 'T00:00:00');
  if (!d || ymd(d) !== value) return '';
  d.setDate(d.getDate() - (weekdayOf(d) - 1));
  return ymd(d);
}

function simpleWeeks(weeks) {
  const m = String(weeks || '').match(/^(\d+)(?:-(\d+))?([单双])?$/);
  return m ? { from: +m[1], to: +(m[2] || m[1]), parity: m[3] || '' }
    : { from: 1, to: Math.max(1, S.settings.totalWeeks - 2), parity: 'custom' };
}

function weekRuleHTML(weeks) {
  const p = simpleWeeks(weeks);
  return '<div class="week-rule">' +
    '<label>从第 <input class="inp s-from" aria-label="上课起始周" type="number" min="1" max="40" value="' + p.from + '"> 周</label>' +
    '<label>到第 <input class="inp s-to" aria-label="上课结束周" type="number" min="1" max="40" value="' + p.to + '"> 周</label>' +
    '<select class="inp s-parity" aria-label="单双周">' +
      [['', '每周'], ['单', '仅单周'], ['双', '仅双周'], ['custom', '自定义周次']].map(x =>
        '<option value="' + x[0] + '"' + (p.parity === x[0] ? ' selected' : '') + '>' + x[1] + '</option>').join('') +
    '</select><label class="week-advanced">周次 <input class="inp s-weeks" aria-label="自定义周次" value="' + esc(weeks || '1-18') + '" placeholder="1-8,10-16"></label></div>';
}

function bindWeekRules(root) {
  $$('.week-rule', root).forEach(row => {
    const update = () => {
      if ($('.s-parity', row).value !== 'custom') {
        $('.s-weeks', row).value = $('.s-from', row).value + '-' + $('.s-to', row).value + $('.s-parity', row).value;
      }
    };
    ['.s-from', '.s-to', '.s-parity'].forEach(sel => $(sel, row).onchange = update);
    $('.s-weeks', row).onchange = () => {
      const p = simpleWeeks($('.s-weeks', row).value.trim());
      $('.s-from', row).value = p.from; $('.s-to', row).value = p.to; $('.s-parity', row).value = p.parity;
    };
  });
}

function weeksFromRule(root) {
  const parity = $('.s-parity', root).value;
  return parity === 'custom' ? $('.s-weeks', root).value.trim()
    : $('.s-from', root).value + '-' + $('.s-to', root).value + parity;
}

function validSessionWeeks(spec, total) {
  if (!/^\d+(?:-\d+)?(?:[,，]\d+(?:-\d+)?)*[单双]?$/.test(spec)) return false;
  const numbers = spec.match(/\d+/g).map(Number);
  if (numbers.some(n => n < 1 || n > total)) return false;
  if (spec.split(/[,，]/).some(part => { const n = part.match(/\d+/g).map(Number); return n.length === 2 && n[0] > n[1]; })) return false;
  const weeks = parseWeeks(spec);
  return !!(weeks && weeks.size);
}

function timetableImportHTML(prefix) {
  return '<div class="tt-import" id="' + prefix + '">' +
    '<div class="f-row"><div class="field"><label for="' + prefix + '-date">开学日期</label>' +
      '<input class="inp ti-date" id="' + prefix + '-date" type="date" value="' + esc(S.settings.termStart) + '">' +
      '<div class="hint">按开学所在周的周一作为第 1 周起点。</div></div>' +
    '<div class="field"><label for="' + prefix + '-weeks">学期总周数</label>' +
      '<input class="inp ti-total" id="' + prefix + '-weeks" type="number" min="1" max="40" value="' + S.settings.totalWeeks + '"></div></div>' +
    '<div class="ti-upload"><label class="btn" for="' + prefix + '-file">' + ic('upload') + '上传课表图片</label>' +
      '<input class="ti-file" id="' + prefix + '-file" type="file" accept="image/png,image/jpeg,image/webp">' +
      '<p class="hint">上传包含星期列和节次栏的清晰整周课表。使用 Windows 本机 OCR，不上传到云端；识别后请核对。</p></div>' +
    '<div class="ti-status" role="status"></div><div class="ti-preview"></div>' +
    '<div class="ti-toolbar"><b>课程草稿</b><button class="btn btn-xs ti-add" type="button">' + ic('plus') + '手动补一门</button></div>' +
    '<div class="ti-rows"></div><details class="ti-raw" hidden><summary>查看识别原文</summary><pre></pre></details>' +
    '<div class="hint mt">确认后追加到课表，不删除已有课程。可以修改课程名称、节次、起止周和单双周。</div></div>';
}

function timetableDraftRow(row, i) {
  return '<div class="ti-course" data-index="' + i + '">' +
    '<div class="f-row"><div class="field"><label>课程名称</label><input class="inp ti-name" aria-label="课程名称" value="' + esc(row.name) + '"></div>' +
    '<div class="field"><label>授课老师</label><input class="inp ti-teacher" aria-label="授课老师" value="' + esc(row.teacher || '') + '"></div>' +
    '<button class="icon-btn ti-remove" type="button" title="移除草稿">' + ic('trash') + '</button></div>' +
    '<div class="ti-session"><label>星期<select class="inp ti-day" aria-label="星期">' + WD.map((w, k) => '<option value="' + (k+1) + '"' + (+row.day === k+1 ? ' selected' : '') + '>周' + w + '</option>').join('') + '</select></label>' +
    '<label>开始节次<input class="inp ti-start" aria-label="开始节次" type="number" min="1" max="' + sections().length + '" value="' + row.start + '"></label>' +
    '<label>连上几节<input class="inp ti-len" aria-label="连上几节" type="number" min="1" max="' + sections().length + '" value="' + row.len + '"></label>' +
    '<label>教室<input class="inp ti-room" aria-label="教室" value="' + esc(row.room || '') + '"></label></div>' +
    weekRuleHTML(row.weeks) + '</div>';
}

function collectTimetableDraft(root) {
  TT_DRAFT.rows = $$('.ti-course', root).map(row => {
    const previous = TT_DRAFT.rows[+row.dataset.index] || {};
    return Object.assign({}, previous, { name: $('.ti-name', row).value.trim(), teacher: $('.ti-teacher', row).value.trim(),
      day: +$('.ti-day', row).value, start: +$('.ti-start', row).value, len: +$('.ti-len', row).value,
      room: $('.ti-room', row).value.trim(), weeks: weeksFromRule(row) });
  });
}

function paintTimetableDraft(root) {
  $('.ti-status', root).textContent = TT_DRAFT.busy ? '正在本机识别，请稍候…' :
    (TT_DRAFT.error || TT_DRAFT.warnings.join(' '));
  $('.ti-status', root).classList.toggle('error', !!TT_DRAFT.error);
  $('.ti-preview', root).innerHTML = TT_DRAFT.image ? '<img alt="上传的课表预览" src="' + TT_DRAFT.image + '">' : '';
  $('.ti-rows', root).innerHTML = TT_DRAFT.rows.map(timetableDraftRow).join('') || '<p class="hint">还没有课程草稿。上传图片识别，或手动补录。</p>';
  const raw = $('.ti-raw', root); raw.hidden = !TT_DRAFT.rawText; $('pre', raw).textContent = TT_DRAFT.rawText;
  $('.ti-file', root).disabled = TT_DRAFT.busy; $('.ti-add', root).disabled = TT_DRAFT.busy;
  bindWeekRules(root);
  $$('.ti-remove', root).forEach(button => button.onclick = () => {
    const index = +button.closest('.ti-course').dataset.index;
    collectTimetableDraft(root); TT_DRAFT.rows.splice(index, 1); paintTimetableDraft(root);
  });
}

async function timetableFileData(file) {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('请上传 PNG、JPG 或 WebP 图片。');
  if (file.size > 15*1024*1024) throw new Error('图片过大，请先裁掉无关内容。');
  const image = await createImageBitmap(file);
  try {
    const scale = Math.min(1, 2400 / Math.max(image.width, image.height));
    const canvas = document.createElement('canvas'); canvas.width = Math.round(image.width*scale); canvas.height = Math.round(image.height*scale);
    const ctx = canvas.getContext('2d'); ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const data = canvas.toDataURL('image/jpeg', .92);
    if (data.length > 5_590_000) throw new Error('图片过大，请换成较小的课表截图。');
    return data;
  } finally { image.close(); }
}

function bindTimetableImport(root) {
  paintTimetableDraft(root);
  $('.ti-add', root).onclick = () => {
    collectTimetableDraft(root);
    TT_DRAFT.rows.push({ name: '', teacher: '', day: 1, start: 1, len: 2, room: '', weeks: '1-' + Math.max(1, +$('.ti-total', root).value - 2) });
    paintTimetableDraft(root);
  };
  $('.ti-file', root).onchange = async e => {
    const file = e.target.files[0]; if (!file) return;
    if (TT_DRAFT.rows.length && !window.confirm('重新识别会替换当前未保存的课程草稿，已有正式课程不受影响。是否继续？')) return;
    TT_DRAFT.busy = true; TT_DRAFT.error = ''; TT_DRAFT.warnings = []; paintTimetableDraft(root);
    try {
      if (!API.connected) throw new Error('图片识别需要本机服务，请双击「启动工作台.bat」。离线版仍可手动补录。');
      const image = await timetableFileData(file); TT_DRAFT.image = image;
      const data = await apiRequest('/api/timetable/recognize', { method: 'POST', body: JSON.stringify({ image: image, totalWeeks: +$('.ti-total', root).value, maxSections: sections().length }) });
      TT_DRAFT.rows = (data.courses || []).flatMap(c => (c.sessions || []).map(s => Object.assign({ name: c.name, teacher: c.teacher, note: c.note }, s)));
      TT_DRAFT.warnings = data.warnings || []; TT_DRAFT.rawText = data.rawText || '';
      if (TT_DRAFT.rows.length) TT_DRAFT.warnings.unshift('识别到 ' + TT_DRAFT.rows.length + ' 个上课时段，请校对后确认。');
    } catch (error) { TT_DRAFT.error = error.message; }
    finally { TT_DRAFT.busy = false; paintTimetableDraft(root); }
  };
}

function commitTimetableDraft(root) {
  if (TT_DRAFT.busy) { toast('请等待识别完成', 'warn'); return false; }
  const monday = termMonday($('.ti-date', root).value), total = +$('.ti-total', root).value;
  if (!monday || !Number.isInteger(total) || total < 1 || total > 40) { toast('请填写有效开学日期和 1–40 周的学期总周数', 'warn'); return false; }
  collectTimetableDraft(root);
  for (const row of TT_DRAFT.rows) {
    if (!row.name || !Number.isInteger(row.start) || !Number.isInteger(row.len) || row.start < 1 || row.len < 1 || row.start+row.len-1 > sections().length || !validSessionWeeks(row.weeks, total)) {
      toast('请检查课程名称、节次、起止周和单双周，不能超出学期范围', 'warn'); return false;
    }
  }
  TT_DRAFT.rows.forEach(row => {
    const id = 'c-img-' + hashStr(row.name + '|' + (row.teacher || ''));
    let course = S.courses.find(c => c.id === id);
    if (!course) { course = normCourse({ id: id, name: row.name, teacher: row.teacher || '', platform: '', color: PALETTE[S.courses.length % PALETTE.length], note: row.note || '', sessions: [] }); S.courses.push(course); }
    const session = { day: row.day, start: row.start, len: row.len, weeks: row.weeks, room: row.room || '' };
    if (!course.sessions.some(s => JSON.stringify(s) === JSON.stringify(session))) course.sessions.push(session);
  });
  S.settings.termStart = monday; S.settings.totalWeeks = total; UI.week = null;
  save(); TT_DRAFT.rows = []; TT_DRAFT.image = ''; TT_DRAFT.warnings = []; TT_DRAFT.rawText = ''; TT_DRAFT.error = '';
  return true;
}

function openTimetableImport() {
  const modal = openModal('导入课表与学期设置', timetableImportHTML('ttImportModal'),
    '<button class="btn" data-close>取消</button><button class="btn btn-primary" id="tiConfirm">确认并保存</button>', { wide: true });
  const root = $('#ttImportModal', modal); bindTimetableImport(root);
  $('[data-close]', modal).onclick = closeModal;
  $('#tiConfirm', modal).onclick = () => { if (commitTimetableDraft(root)) { closeModal(); render(); toast('课表与学期设置已保存', 'ok'); } };
}
