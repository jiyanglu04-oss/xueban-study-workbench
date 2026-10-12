/* ============================================================
   学伴 · 03 课表 & 待办
   ============================================================ */

function weekHours() {
  const w = UI.week == null ? weekOf(new Date()) : UI.week;
  let n = 0;
  for (let d = 1; d <= 7; d++) sessionsOn(w, d).forEach(x => n += x.s.len);
  return Math.round(n * 0.75 * 10) / 10;
}

function weekendBusy(w) {
  // 有调课落在周末时，周末两列必须露出来，否则那一周会显得「没这门课」。
  for (let d = 6; d <= 7; d++) if (sessionsOn(w, d).length) return true;
  return false;
}

function renderTT() {
  const now = new Date();
  const curW = Math.max(1, Math.min(S.settings.totalWeeks, weekOf(now)));
  const w = UI.week == null ? curW : Math.max(1, Math.min(S.settings.totalWeeks, UI.week));
  const forcedWeekend = weekendBusy(w);
  const days = (S.settings.showWeekend || forcedWeekend) ? 7 : 5;
  const rows = sections().length;
  UI.week = w;
  // 「在修课程」只算真的排了课的——平台同步过来的课程没有课表时段，
  // 全算进去会把这门数撑到三十几，看着像坏了。
  const withSess = S.courses.filter(c => (c.sessions || []).length).length;

  let html = '<div class="card"><div class="card-h" style="flex-wrap:wrap">' +
    '<h3>' + ic('cal') + ' 第 ' + w + ' 周' + (w === curW ? ' <span class="badge b-ok" style="height:18px">本周</span>' : '') +
      (forcedWeekend && !S.settings.showWeekend
        ? ' <span class="badge b-info" style="height:18px">本周含周末课</span>' : '') + '</h3>' +
    '<div class="sp">' +
      '<button class="btn btn-sm" id="ttImport">' + ic('upload') + '导入课表图片</button>' +
      '<div class="seg"><button data-wk="-1">‹ 上周</button><button data-wk="0">本周</button><button data-wk="1">下周 ›</button></div>' +
      '<span class="pill" style="height:31px;font-size:12px">' +
        (dateOf(w, 1) ? (dateOf(w, 1).getMonth() + 1) + '/' + dateOf(w, 1).getDate() : '') + ' — ' +
        (dateOf(w, days) ? (dateOf(w, days).getMonth() + 1) + '/' + dateOf(w, days).getDate() : '') + '</span>' +
      '<label class="switch' + (days === 7 ? ' on' : '') + '" id="swWeekend" style="padding:0;gap:7px">' +
        '<span class="sw" style="transform:scale(.84)"></span>' +
        '<span class="tx" style="font-size:12.5px;font-weight:600">周末</span></label>' +
    '</div></div>';

  html += '<div class="card-b"><div class="tt-wrap"><div class="tt" id="ttGrid" ' +
    'style="grid-template-columns:58px repeat(' + days + ',minmax(0,1fr));grid-auto-rows:46px">';

  html += '<div style="grid-row:1;grid-column:1"></div>';
  for (let d = 1; d <= days; d++) {
    const dt = dateOf(w, d);
    const isToday = dt && ymd(dt) === ymd(now);
    html += '<div class="tt-hd' + (isToday ? ' today' : '') + '" style="grid-row:1;grid-column:' + (d + 1) + '">星期' + WD[d - 1] +
      '<span>' + (dt ? (dt.getMonth() + 1) + '/' + dt.getDate() : '') + '</span></div>';
  }
  for (let r = 1; r <= rows; r++) {
    const t = secTime(r);
    html += '<div class="tt-tcol" style="grid-row:' + (r + 1) + ';grid-column:1"><b>' + r + '</b>' + t.start + '<br>' + t.end + '</div>';
    for (let d = 1; d <= days; d++) {
      html += '<div class="tt-cell" data-cell="' + d + '-' + r + '" style="grid-row:' + (r + 1) + ';grid-column:' + (d + 1) + '"></div>';
    }
  }
  for (let d = 1; d <= days; d++) {
    sessionsOn(w, d).forEach(x => {
      const c = x.c, s = x.s;
      html += '<div class="tt-ev" data-cid="' + c.id + '" title="' + esc(c.name + (c.teacher ? ' · ' + c.teacher : '') + (s.room ? ' · ' + s.room : '')) + '" ' +
        'style="grid-row:' + (s.start + 1) + ';grid-column:' + (d + 1) + ';grid-row-end:span ' + Math.max(1, s.len) +
        ';background:' + hexA(c.color, 0.14) + ';border-left-color:' + c.color + ';z-index:3">' +
        '<b style="color:' + c.color + '">' + esc(c.name) + '</b>' +
        (s.room ? '<span style="color:' + c.color + '">' + esc(s.room) + '</span>' : '') +
        (c.teacher ? '<span style="color:' + c.color + '">' + esc(c.teacher) + '</span>' : '') +
        '</div>';
    });
  }
  html += '</div></div>';

  // 图例只列「这一周真的会上」的课；否则平台同步来的一堆没排课的课程会把图例刷爆。
  const weekCourses = [];
  for (let d = 1; d <= days; d++) {
    sessionsOn(w, d).forEach(x => { if (!weekCourses.some(o => o.id === x.c.id)) weekCourses.push(x.c); });
  }
  if (weekCourses.length) {
    html += '<div class="tt-legend">' + weekCourses.map(c =>
      '<span class="tt-lg" data-cid="' + c.id + '"><i style="background:' + c.color + '"></i>' + esc(c.name) + '</span>').join('') + '</div>';
  }
  html += '</div></div>';

  html += '<div class="grid g-3 mt">' +
    '<div class="card"><div class="card-b" style="display:flex;gap:12px;align-items:center">' +
      '<div class="kpi-ic" style="background:#ECE0CC;color:#8B6F47">' + ic('book') + '</div>' +
      '<div><div class="kpi-v">' + withSess + '</div><div class="kpi-k">在修课程</div></div></div></div>' +
    '<div class="card"><div class="card-b" style="display:flex;gap:12px;align-items:center">' +
      '<div class="kpi-ic" style="background:#E5EBD9;color:#5F7A4A">' + ic('clock') + '</div>' +
      '<div><div class="kpi-v">' + weekHours() + '<span style="font-size:14px;font-weight:600"> h</span></div><div class="kpi-k">本周课时</div></div></div></div>' +
    '<div class="card"><div class="card-b" style="display:flex;gap:12px;align-items:center">' +
      '<div class="kpi-ic" style="background:#F7E8D1;color:#B8762B">' + ic('warn') + '</div>' +
      '<div><div class="kpi-v">' + Math.max(0, S.settings.totalWeeks - 18) + '<span style="font-size:14px;font-weight:600"> 周</span></div><div class="kpi-k">考试周</div></div></div></div>' +
    '</div>' +
    '<div class="hint mt">点空白格子可以快速加课；点课程块可以查看详情、进入对应平台。周次支持「1-18」「1-16单」「2-16双」等写法。</div>';

  $('#view').innerHTML = html;
  $('#ttImport').onclick = openTimetableImport;

  $$('[data-wk]').forEach(b => b.onclick = () => {
    const v = +b.dataset.wk;
    UI.week = v === 0 ? curW : w + v;
    UI.week = Math.max(1, Math.min(S.settings.totalWeeks, UI.week));
    renderTT();
  });
  const swv = $('#swWeekend');
  if (swv) swv.onclick = () => { S.settings.showWeekend = !S.settings.showWeekend; save(); renderTT(); };
  $$('#ttGrid .tt-cell').forEach(cell => cell.onclick = () => {
    const parts = cell.dataset.cell.split('-');
    editCourse(null, { day: +parts[0], start: +parts[1], len: 2, weeks: '1-' + (S.settings.totalWeeks - 2), room: '' }, w);
  });
  $$('#ttGrid .tt-ev, .tt-lg').forEach(e => e.onclick = ev => { ev.stopPropagation(); openCourse(e.dataset.cid); });
}

/* ==================== 待办 ==================== */
function todoHTML(t) {
  const c = courseOf(t.courseId) || courseOf(t.course);
  const pcls = ['', 'b-p1', 'b-p2', 'b-p3'][t.priority] || 'b-p3';
  const pl = ['', '高', '中', '低'][t.priority] || '中';
  const srcPlat = PLAT[t.source];
  let dueTxt = fmtDue(t.due), dueCls = t.done ? 'ok' : dueClass(t.due);
  if (t.done && t.doneAt) { dueTxt = '已完成 · ' + relTime(t.doneAt); dueCls = 'ok'; }
  return '<div class="row' + (t.done ? ' done' : '') + '" data-tid="' + t.id + '">' +
    '<div class="check' + (t.done ? ' on' : '') + '" data-toggle="' + t.id + '">' + ic('check') + '</div>' +
    '<div class="row-main"><div class="row-title">' + esc(t.title) + '</div>' +
      '<div class="row-meta">' +
        '<span class="due ' + dueCls + '">' + dueTxt + '</span>' +
        (c ? '<span style="color:' + c.color + ';font-weight:650">' + esc(c.name) + '</span>' : '') +
        (srcPlat ? '<span class="badge b-info" style="height:17px;font-size:10px">' + esc(srcPlat.name) + '</span>' : '') +
      '</div></div>' +
    '<span class="badge ' + pcls + '">' + pl + '</span>' +
    (t.url ? '<a class="btn btn-xs" href="' + esc(t.url) + '" target="_blank" rel="noopener">打开</a>' : '') +
    '<div class="row-act">' +
      '<button class="icon-btn" data-edit-todo="' + t.id + '" title="编辑" style="width:28px;height:28px">' + ic('pencil') + '</button>' +
      '<button class="icon-btn" data-del-todo="' + t.id + '" title="删除" style="width:28px;height:28px">' + ic('trash') + '</button>' +
    '</div></div>';
}

function renderTodos() {
  const now = new Date();
  let list = S.todos.slice();
  const f = UI.todoFilter;
  if (f === 'open') list = list.filter(t => !t.done);
  else if (f === 'today') list = list.filter(t => { const d = parseD(t.due); return !t.done && d && daysBetween(now, d) === 0; });
  else if (f === 'week') list = list.filter(t => { const d = parseD(t.due); return !t.done && d && daysBetween(now, d) >= 0 && daysBetween(now, d) <= 7; });
  else if (f === 'over') list = list.filter(t => { const d = parseD(t.due); return !t.done && d && d < now; });
  else if (f === 'done') list = list.filter(t => t.done);

  list.sort((a, b) => {
    if (a.done !== b.done) return a.done ? 1 : -1;
    const da = parseD(a.due), db = parseD(b.due);
    if (!da && !db) return (a.priority || 2) - (b.priority || 2);
    if (!da) return 1;
    if (!db) return -1;
    if (+da === +db) return (a.priority || 2) - (b.priority || 2);
    return da - db;
  });

  const counts = {
    open: openTodos().length,
    today: S.todos.filter(t => { const d = parseD(t.due); return !t.done && d && daysBetween(now, d) === 0; }).length,
    week: S.todos.filter(t => { const d = parseD(t.due); return !t.done && d && daysBetween(now, d) >= 0 && daysBetween(now, d) <= 7; }).length,
    over: overdueTodos().length,
    done: S.todos.filter(t => t.done).length,
    all: S.todos.length
  };
  const chips = [['open', '进行中'], ['today', '今天'], ['week', '本周'], ['over', '已逾期'], ['done', '已完成'], ['all', '全部']];

  let body = '';
  if (!list.length) {
    body = emptyHTML('check', UI.todoFilter === 'open' ? '没有进行中的待办，轻松一下' : '这个分类下没有内容');
  } else {
    const groups = {};
    list.forEach(t => {
      const d = parseD(t.due);
      let k;
      if (t.done) k = '已完成';
      else if (!d) k = '未设截止';
      else {
        const dd = daysBetween(now, d);
        if (dd < 0) k = '已逾期';
        else if (dd === 0) k = '今天';
        else if (dd === 1) k = '明天';
        else if (dd <= 7) k = '本周内';
        else k = '更晚';
      }
      (groups[k] = groups[k] || []).push(t);
    });
    const order = ['已逾期', '今天', '明天', '本周内', '更晚', '未设截止', '已完成'];
    body = order.filter(k => groups[k]).map(k =>
      '<div style="padding:12px 14px 2px;font-size:11.5px;font-weight:700;color:var(--text-3);letter-spacing:.05em">' +
      esc(k) + ' <span style="opacity:.7">· ' + groups[k].length + '</span></div>' +
      groups[k].map(todoHTML).join('')
    ).join('');
  }

  const donePct = S.todos.length ? Math.round(counts.done / S.todos.length * 100) : 0;

  $('#view').innerHTML =
    '<div class="card mb"><div class="card-b" style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">' +
      '<div style="flex:1;min-width:200px">' +
        '<div style="display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:6px">' +
          '<span class="muted">完成进度</span><b>' + counts.done + ' / ' + S.todos.length + ' · ' + donePct + '%</b></div>' +
        '<div class="bar"><i style="width:' + donePct + '%"></i></div>' +
      '</div>' +
      (counts.over ? '<span class="badge b-p1">' + ic('warn') + ' ' + counts.over + ' 项已逾期</span>' : '<span class="badge b-ok">' + ic('check') + ' 没有逾期任务</span>') +
    '</div></div>' +

    '<div class="card"><div class="card-h" style="flex-wrap:wrap;gap:10px">' +
      '<h3>' + ic('check') + ' 共 ' + S.todos.length + ' 项</h3>' +
      '<div class="sp" style="flex-wrap:wrap">' +
        chips.map(c => '<button class="chip' + (UI.todoFilter === c[0] ? ' on' : '') + '" data-tf="' + c[0] + '">' + c[1] +
          '<span class="n">' + counts[c[0]] + '</span></button>').join('') +
      '</div></div>' +
      '<div class="card-b flush">' + body + '</div></div>' +
    '<div class="hint mt">从学习通 / 雨课堂 / MOOC 同步来的作业会自动出现在这里，并带上来源标签；也可以把消息一键「转待办」。</div>';

  $$('[data-tf]').forEach(b => b.onclick = () => { UI.todoFilter = b.dataset.tf; renderTodos(); });
  bindTodoEvents();
}

function bindTodoEvents() {
  $$('[data-toggle]').forEach(el => el.onclick = e => {
    e.stopPropagation();
    const t = S.todos.find(x => x.id === el.dataset.toggle);
    if (!t) return;
    t.done = !t.done;
    t.doneAt = t.done ? new Date().toISOString() : null;
    save();
    render();
    if (t.done) toast('已完成：' + t.title, 'ok');
  });
  $$('[data-edit-todo]').forEach(el => el.onclick = e => {
    e.stopPropagation();
    editTodo(S.todos.find(x => x.id === el.dataset.editTodo));
  });
  $$('[data-del-todo]').forEach(el => el.onclick = e => {
    e.stopPropagation();
    const t = S.todos.find(x => x.id === el.dataset.delTodo);
    if (!t) return;
    confirmBox('删除待办', '确定删除「' + esc(t.title) + '」吗？此操作不可撤销。'
      + (String(t.source || '') !== 'manual'
        ? '<br><span class="hint">这条是同步自动生成的。删掉之后同一份通知不会再把它变回来。</span>' : ''), () => {
      dismissId(t.id);           // 记下来，免得下次同步又被自动拉回来
      S.todos = S.todos.filter(x => x.id !== t.id);
      save(); render(); toast('已删除', 'ok');
    }, '删除');
  });
}

function defaultDue(offsetDays) {
  const d = new Date();
  d.setDate(d.getDate() + (offsetDays == null ? 1 : offsetDays));
  d.setHours(23, 59, 0, 0);
  return ymd(d) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

function editTodo(t) {
  const isNew = !t;
  const cur = t || normTodo({ priority: 2, due: defaultDue() });
  const courseOpts = '<option value="">（不关联课程）</option>' + courseOptionsFor(cur).map(c =>
    '<option value="' + c.id + '"' + ((cur.courseId === c.id || cur.course === c.name) ? ' selected' : '') + '>' + esc(c.name) + '</option>').join('');

  const m = openModal(isNew ? '新建待办' : '编辑待办',
    '<div class="field"><label>任务内容</label>' +
      '<input class="inp" id="fTitle" placeholder="例如：完成数据结构第 3 章作业" value="' + esc(cur.title === '(未命名)' ? '' : cur.title) + '"></div>' +
    '<div class="f-row">' +
      '<div class="field"><label>截止时间</label><input class="inp" type="datetime-local" id="fDue" value="' + esc(cur.due) + '"></div>' +
      '<div class="field"><label>优先级</label><select class="inp" id="fPri">' +
        [1, 2, 3].map(p => '<option value="' + p + '"' + (cur.priority === p ? ' selected' : '') + '>' + ['', '高', '中', '低'][p] + '</option>').join('') +
      '</select></div>' +
    '</div>' +
    '<div class="field"><label>关联课程</label><select class="inp" id="fCourse">' + courseOpts + '</select></div>' +
    '<div class="field"><label>备注</label><textarea class="inp" id="fNote" placeholder="可选：作业范围、提交方式等">' + esc(cur.note) + '</textarea></div>',
    '<button class="btn" data-close>取消</button><button class="btn btn-primary" id="fSave">' + (isNew ? '添加' : '保存') + '</button>');

  $('[data-close]', m).onclick = closeModal;
  $('#fSave', m).onclick = () => {
    const title = $('#fTitle', m).value.trim();
    if (!title) { toast('请填写任务内容', 'warn'); return; }
    const cid = $('#fCourse', m).value;
    const c = S.courses.find(x => x.id === cid);
    const data = {
      title: title,
      due: $('#fDue', m).value,
      priority: +$('#fPri', m).value,
      courseId: cid,
      course: c ? c.name : '',
      note: $('#fNote', m).value.trim()
    };
    if (isNew) {
      S.todos.push(normTodo(Object.assign({ id: uid('t'), source: 'manual' }, data)));
      toast('已添加待办', 'ok');
    } else {
      Object.assign(t, data);
      toast('已保存', 'ok');
    }
    save(); closeModal(); render();
  };
}
