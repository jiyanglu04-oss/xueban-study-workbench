/* ============================================================
   学伴 · 04 消息中心 & 课程管理
   ============================================================ */

const KIND_MAP = {
  notice: ['公告', 'b-info'],
  homework: ['作业', 'b-p2'],
  exam: ['考试', 'b-p1'],
  signin: ['签到', 'b-ok']
};

function msgHTML(m, compact) {
  const p = PLAT[m.platform] || { name: m.platform, short: '?', color: '#8A7A63' };
  const c = courseOf(m.courseId) || courseOf(m.course);
  const k = KIND_MAP[m.kind] || ['通知', 'b-p3'];
  return '<div class="msg' + (m.read ? '' : ' unread') + '" data-mid="' + m.id + '">' +
    '<div class="msg-plat" style="background:' + p.color + '">' + esc(p.short) + '</div>' +
    '<div class="msg-b">' +
      '<div class="msg-t">' + (m.read ? '' : '<span class="unread-dot"></span>') + esc(m.title) +
        '<span class="badge ' + k[1] + '" style="height:17px;font-size:10px">' + k[0] + '</span>' +
        (c ? '<span style="font-size:11px;font-weight:600;color:' + c.color + '">' + esc(c.name) + '</span>' : '') + '</div>' +
      (m.content ? '<div class="msg-c">' + esc(m.content) + '</div>' : '') +
      '<div class="msg-m">' +
        '<span style="color:' + p.color + ';font-weight:650">' + esc(p.name) + '</span>' +
        '<span>' + relTime(m.time) + '</span>' +
        (m.deadline ? '<span class="due ' + dueClass(m.deadline) + '">截止 ' + fmtDue(m.deadline) + '</span>' : '') +
        (m.url ? '<a href="' + esc(m.url) + '" target="_blank" rel="noopener" style="font-weight:650">去处理 →</a>' : '') +
        (compact ? '' : '<button class="btn btn-xs btn-ghost" data-mtoggle="' + m.id + '">' + (m.read ? '标为未读' : '标为已读') + '</button>') +
        (compact ? '' : '<button class="btn btn-xs btn-ghost" data-mtodo="' + m.id + '">转待办</button>') +
        (compact ? '' : '<button class="btn btn-xs btn-ghost" data-mdel="' + m.id + '">删除</button>') +
      '</div>' +
    '</div></div>';
}

function renderInbox() {
  let list = S.messages.slice();
  if (UI.msgPlatform !== 'all') list = list.filter(m => m.platform === UI.msgPlatform);
  if (UI.msgUnreadOnly) list = list.filter(m => !m.read);
  if (UI.msgQuery) {
    const q = UI.msgQuery.toLowerCase();
    list = list.filter(m => (m.title + ' ' + m.content + ' ' + m.course).toLowerCase().indexOf(q) >= 0);
  }
  list.sort((a, b) => (parseD(b.time) || 0) - (parseD(a.time) || 0));

  const counts = {};
  S.messages.forEach(m => { counts[m.platform] = (counts[m.platform] || 0) + 1; });

  $('#view').innerHTML =
    '<div class="card"><div class="card-h" style="flex-wrap:wrap;gap:10px">' +
      '<h3>' + ic('inbox') + ' 全部消息 <span class="dim" style="font-weight:500">' + S.messages.length + '</span></h3>' +
      '<div class="sp">' +
        '<input class="inp" id="msgQ" placeholder="搜索标题 / 内容 / 课程" value="' + esc(UI.msgQuery) + '" style="width:220px;height:30px">' +
        '<button class="chip' + (UI.msgUnreadOnly ? ' on' : '') + '" id="unreadOnly">仅未读</button>' +
        '<button class="btn btn-sm" id="markAll">全部已读</button>' +
      '</div></div>' +
      '<div class="card-b" style="padding:12px 14px 10px;display:flex;gap:7px;flex-wrap:wrap;border-bottom:1px solid var(--border)">' +
        '<button class="chip' + (UI.msgPlatform === 'all' ? ' on' : '') + '" data-mp="all">全部<span class="n">' + S.messages.length + '</span></button>' +
        PLATFORMS.filter(p => counts[p.key]).map(p =>
          '<button class="chip' + (UI.msgPlatform === p.key ? ' on' : '') + '" data-mp="' + p.key + '">' +
          '<i style="width:7px;height:7px;border-radius:50%;background:' + p.color + ';display:block"></i>' +
          esc(p.name) + '<span class="n">' + counts[p.key] + '</span></button>').join('') +
      '</div>' +
      '<div class="card-b flush">' +
        (list.length ? list.map(m => msgHTML(m, false)).join('')
                     : emptyHTML('inbox', S.messages.length ? '没有符合条件的消息' : '收件箱是空的')) +
      '</div></div>' +
    (S.messages.length ? '' :
      '<div class="card mt"><div class="card-b" style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
      '<div class="kpi-ic" style="background:#ECE0CC;color:#8B6F47;flex:0 0 42px">' + ic('bolt') + '</div>' +
      '<div style="flex:1;min-width:230px"><b style="font-size:13.5px">怎么让消息自动进来？</b>' +
      '<p class="hint" style="margin-top:5px">在工作台文件夹里双击 <b>一键同步数据.bat</b>，首次会让你扫码登录学习通 / 雨课堂 / MOOC，' +
      '之后每次运行都会自动抓取新消息并写入本工作台。也可以在「平台入口」页手动录入微助教、微信群里的通知。</p></div>' +
      '<button class="btn btn-primary btn-sm" data-synchelp>查看步骤</button></div></div>');

  const q = $('#msgQ');
  q.oninput = e => {
    UI.msgQuery = e.target.value;
    const pos = e.target.selectionStart;
    renderInbox();
    const q2 = $('#msgQ');
    q2.focus();
    q2.setSelectionRange(pos, pos);
  };
  $('#unreadOnly').onclick = () => { UI.msgUnreadOnly = !UI.msgUnreadOnly; renderInbox(); };
  $('#markAll').onclick = () => {
    S.messages.forEach(m => { m.read = true; });
    save(); render(); toast('已全部标为已读', 'ok');
  };
  $$('[data-mp]').forEach(b => b.onclick = () => { UI.msgPlatform = b.dataset.mp; renderInbox(); });
  const sh = $('[data-synchelp]');
  if (sh) sh.onclick = showSyncHelp;

  $$('.msg').forEach(el => el.onclick = () => {
    const m = S.messages.find(x => x.id === el.dataset.mid);
    if (m && !m.read) { m.read = true; save(); renderSidebar(); renderTopbar(); el.classList.remove('unread'); }
  });
  $$('[data-mtoggle]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const m = S.messages.find(x => x.id === b.dataset.mtoggle);
    if (m) { m.read = !m.read; save(); render(); }
  });
  $$('[data-mdel]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    dismissId(b.dataset.mdel);   // 记下来，免得下次同步又把这条拉回来
    S.messages = S.messages.filter(x => x.id !== b.dataset.mdel);
    save(); render(); toast('已删除', 'ok');
  });
  $$('[data-mtodo]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const m = S.messages.find(x => x.id === b.dataset.mtodo);
    if (!m) return;
    S.todos.push(normTodo({
      title: m.title, due: m.deadline || defaultDue(),
      priority: m.kind === 'homework' ? 1 : 2,
      courseId: m.courseId, course: m.course,
      source: m.platform, url: m.url, note: String(m.content || '').slice(0, 300)
    }));
    save(); toast('已转为待办', 'ok'); render();
  });
}

/* ==================== 课程管理 ==================== */

/* 平台抓来的课程详情（目前只有中国大学 MOOC 会带 detail）。
   以前适配器只调了一个「最近在学的课」接口、拿到课名就收工了，
   所以这里永远是空的 —— 点进课程什么也看不到。
   详情要靠 sync/adapters/icourse163.py 真的去读课程结构接口才会出现。 */
function courseDetailHTML(c) {
  const d = c.detail;
  if (!d || typeof d !== 'object') return '';
  const pr = d.progress || {};
  const done = +pr.done || 0, total = +pr.total || 0;
  const pct = total ? Math.round(done / total * 100) : 0;
  const endD = parseD(d.endAt);
  const ended = !!(endD && endD.getTime() < Date.now());
  const chapters = d.chapters || [], quizzes = d.quizzes || [], exams = d.exams || [];

  let h = '<div class="sec-title">平台课程详情' +
    (d.fetchedAt ? '<span class="dim" style="font-size:11.5px;font-weight:400">同步于 ' + esc(relTime(d.fetchedAt)) + '</span>' : '') +
    '</div>';

  if (d.startAt || d.endAt) {
    h += '<div class="row"><div class="row-main"><div class="row-title">' +
      esc((d.startAt || '?') + ' ~ ' + (d.endAt || '?')) +
      (ended ? '<span class="badge b-p3">已结束</span>' : '<span class="badge b-ok">进行中</span>') +
      '</div><div class="row-meta"><span>' + chapters.length + ' 章</span>' +
      '<span>' + quizzes.length + ' 个章节测验</span>' +
      '<span>' + exams.length + ' 场考试</span></div></div></div>';
  } else if (chapters.length) {
    h += '<div class="row"><div class="row-main"><div class="row-meta">' +
      '<span>' + chapters.length + ' 章</span><span>' + quizzes.length + ' 个章节测验</span></div></div></div>';
  }

  if (total) {
    h += '<div class="row"><div class="row-main">' +
      '<div class="row-title">学习进度 ' + done + ' / ' + total + ' 讲' +
        (done >= total ? '<span class="badge b-ok">已看完</span>' : '') + '</div>' +
      '<div style="height:8px;border-radius:4px;background:var(--surface-3);overflow:hidden;margin-top:7px">' +
        '<i style="display:block;height:100%;width:' + (pct ? pct : 2) + '%;background:' +
        (done >= total ? 'var(--green)' : (done ? 'var(--primary)' : 'var(--orange)')) + '"></i>' +
      '</div></div></div>';
  }

  if (chapters.length) {
    h += '<div class="sec-title">章节 · ' + chapters.length + ' 章</div>' +
      '<div style="max-height:200px;overflow:auto">' + chapters.map(ch => {
        const t = +ch.lessons || 0, dn = +ch.done || 0;
        return '<div class="row"><div class="row-main"><div class="row-title">' + esc(ch.name) + '</div>' +
          '<div class="row-meta"><span>' + t + ' 讲</span><span>' +
          (dn ? '已看 ' + dn : '未开始') + '</span></div></div></div>';
      }).join('') + '</div>';
  }

  if (quizzes.length) {
    h += '<div class="sec-title">章节测验 · ' + quizzes.length + ' 个</div>' +
      '<div style="max-height:200px;overflow:auto">' + quizzes.map(q =>
        '<div class="row"><div class="row-main"><div class="row-title">' + esc(q.name) + '</div>' +
        (q.due ? '<div class="row-meta"><span>截止 ' + esc(q.due) + '</span></div>' : '') +
        '</div></div>').join('') + '</div>';
  }

  if (exams.length) {
    h += '<div class="sec-title">考试 · ' + exams.length + ' 场</div>' + exams.map(e => {
      const ed = parseD(e.due);
      const past = !!(ed && ed.getTime() < Date.now());
      return '<div class="row"><div class="row-main"><div class="row-title">' + esc(e.name) +
        (ed ? '<span class="badge ' + (past ? 'b-p3' : 'b-p2') + '">' +
          (past ? '已截止 ' : '截止 ') + esc(e.due) + '</span>' : '') +
        '</div>' +
        (e.description ? '<div class="row-meta" style="display:block;line-height:1.65;margin-top:4px">' +
          esc(e.description) + '</div>' : '') +
        '</div></div>';
    }).join('');
  }
  return h;
}

function courseCard(c) {
  const full = '1-' + (S.settings.totalWeeks - 2);
  const sess = (c.sessions || []).map(s => '周' + WD[s.day - 1] + ' 第' + s.start + '-' + (s.start + s.len - 1) + '节' +
    (s.weeks && s.weeks !== full ? ' (' + s.weeks + ')' : '') + (s.room ? ' ' + s.room : '')).join('；');
  const p = PLAT[c.platform];
  const nTodo = S.todos.filter(t => !t.done && (t.courseId === c.id || t.course === c.name)).length;
  const nMsg = S.messages.filter(m => m.courseId === c.id || m.course === c.name).length;
  return '<div class="course" data-cid="' + c.id + '" style="--c:' + c.color + '">' +
    '<div class="course-t">' + esc(c.name) +
      (nTodo ? '<span class="badge b-p2" style="margin-left:8px;height:18px">' + nTodo + ' 待办</span>' : '') + '</div>' +
    '<div class="course-m">' +
      (c.teacher ? '<i>' + ic('user') + esc(c.teacher) + '</i>' : '') +
      (sess ? '<i>' + ic('clock') + esc(sess) + '</i>' : '<i>' + ic('clock') + '<span class="dim">未排课</span></i>') +
      (c.credits ? '<i>' + ic('file') + esc(c.credits) + ' 学分</i>' : '') +
      (c.school ? '<i>' + ic('target') + esc(c.school) + '</i>' : '') +
      (c.detail && c.detail.progress && c.detail.progress.total
        ? '<i>' + ic('check') + '进度 ' + (+c.detail.progress.done || 0) + '/' + c.detail.progress.total + ' 讲</i>' : '') +
      (p ? '<i>' + ic('link') + esc(p.name) + '</i>' : '') +
      (nMsg ? '<i>' + ic('inbox') + nMsg + ' 条消息</i>' : '') +
    '</div>' +
    '<div class="course-a">' +
      (c.url ? '<a class="btn btn-xs btn-primary" href="' + esc(c.url) + '" target="_blank" rel="noopener">进入课程</a>' : '') +
      (!c.url && p && p.home ? '<a class="btn btn-xs btn-primary" href="' + esc(p.home) + '" target="_blank" rel="noopener">打开' + esc(p.name) + '</a>' : '') +
      '<button class="btn btn-xs" data-cedit="' + c.id + '">编辑</button>' +
      '<button class="btn btn-xs btn-danger" data-cdel="' + c.id + '">删除</button>' +
    '</div></div>';
}

function renderCourses() {
  const mine = myCourses().length;
  const all = S.courses.length;
  const hidden = Math.max(0, all - mine);
  /* 默认只看本学期在上的课；平台同步回来的课程池切到「全部」才显示。 */
  const base = UI.courseAll ? S.courses.slice() : myCourses();
  let list = base;
  if (UI.courseQuery) {
    const q = UI.courseQuery.toLowerCase();
    list = list.filter(c => (c.name + ' ' + c.teacher + ' ' + (c.note || '')).toLowerCase().indexOf(q) >= 0);
  }
  const totalCredits = base.reduce((n, c) => n + (parseFloat(c.credits) || 0), 0);

  const tabs = '<div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">' +
    '<button class="chip' + (UI.courseAll ? '' : ' on') + '" id="cTabMine">本学期<span class="n">' + mine + '</span></button>' +
    '<button class="chip' + (UI.courseAll ? ' on' : '') + '" id="cTabAll">全部<span class="n">' + all + '</span></button>' +
    (UI.courseAll && hidden
      ? '<span class="dim" style="font-size:12px">其中 ' + hidden + ' 门来自平台同步，' +
        '多为往期课程、可以删掉</span>'
      : '') +
    '</div>';

  $('#view').innerHTML =
    '<div class="card mb"><div class="card-h" style="flex-wrap:wrap;gap:10px">' +
      '<h3>' + ic('book') + ' ' + (UI.courseAll ? '全部课程' : '本学期课程') +
        ' · ' + base.length + ' 门' +
        (totalCredits ? ' · ' + (Math.round(totalCredits * 10) / 10) + ' 学分' : '') + '</h3>' +
      '<div class="sp">' +
        '<input class="inp" id="cQ" placeholder="搜索课程 / 老师" value="' + esc(UI.courseQuery) + '" style="width:180px;height:30px">' +
        '<button class="btn btn-sm btn-primary" id="addCourse">' + ic('plus') + '新增课程</button>' +
      '</div></div>' +
      '<div class="card-b" style="padding:11px 14px;border-top:1px solid var(--border)">' + tabs + '</div></div>' +
    (base.length
      ? (list.length ? '<div class="grid g-auto">' + list.map(courseCard).join('') + '</div>'
                     : '<div class="card"><div class="card-b">' + emptyHTML('search', '没有匹配的课程') + '</div></div>')
      : '<div class="card"><div class="card-b">' + emptyHTML('book', '还没有课程。手动新增，或者在课表里点空白格子快速添加。') +
        '<div style="text-align:center"><button class="btn btn-primary mt" id="addCourse2">' + ic('plus') + '新增第一门课程</button></div></div></div>') +
    (UI.courseAll
      ? '<div class="hint mt">这里的「平台同步课程」是学习通 / 雨课堂 / MOOC 的课程池，包含往期课程 —— 它们没有课表时段，不参与课表统计。只想过一遍本学期在上的，切回上面的「本学期」。</div>'
      : (hidden
          ? '<div class="hint mt">另有 ' + hidden + ' 门平台同步的往期课程被收起，需要查看或清理时点上面的「全部」。</div>'
          : '<div class="hint mt">提示：「进入课程」链接建议填该课程在平台上的主页地址，之后就能一键跳转，不用再到处找。</div>'));

  const t1 = $('#cTabMine'), t2 = $('#cTabAll');
  if (t1) t1.onclick = () => { UI.courseAll = false; renderCourses(); };
  if (t2) t2.onclick = () => { UI.courseAll = true; renderCourses(); };

  const cq = $('#cQ');
  cq.oninput = e => {
    UI.courseQuery = e.target.value;
    const pos = e.target.selectionStart;
    renderCourses();
    const c2 = $('#cQ');
    c2.focus();
    c2.setSelectionRange(pos, pos);
  };
  const a1 = $('#addCourse'), a2 = $('#addCourse2');
  if (a1) a1.onclick = () => editCourse(null);
  if (a2) a2.onclick = () => editCourse(null);
  $$('.course').forEach(el => el.onclick = e => {
    if (e.target.closest('a,button')) return;
    openCourse(el.dataset.cid);
  });
  $$('[data-cedit]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    editCourse(S.courses.find(x => x.id === b.dataset.cedit));
  });
  $$('[data-cdel]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const c = S.courses.find(x => x.id === b.dataset.cdel);
    if (!c) return;
    confirmBox('删除课程', '确定删除「' + esc(c.name) + '」及其课表排课吗？关联的待办和消息会保留下来。', () => {
      S.courses = S.courses.filter(x => x.id !== c.id);
      save(); render(); toast('已删除课程', 'ok');
    }, '删除');
  });
}

function sessRowHTML(s, i) {
  const maxSec = sections().length;
  let dayOpts = '';
  for (let k = 1; k <= 7; k++) dayOpts += '<option value="' + k + '"' + (+s.day === k ? ' selected' : '') + '>周' + WD[k - 1] + '</option>';
  let startOpts = '';
  for (let k = 1; k <= maxSec; k++) startOpts += '<option value="' + k + '"' + (+s.start === k ? ' selected' : '') + '>' + k + '</option>';
  let lenOpts = '';
  Array.from({ length: maxSec }, (_, n) => n + 1).forEach(function (l) { lenOpts += '<option value="' + l + '"' + (+s.len === l ? ' selected' : '') + '>' + l + ' 节</option>'; });
  return '<div class="sess-row" style="display:flex;gap:7px;align-items:center;margin-bottom:7px;flex-wrap:wrap">' +
    '<select class="inp s-day" aria-label="上课星期" style="width:80px;flex:0 0 80px">' + dayOpts + '</select>' +
    '<span class="dim" style="font-size:12px">第</span>' +
    '<select class="inp s-start" aria-label="开始节次" style="width:64px;flex:0 0 64px">' + startOpts + '</select>' +
    '<select class="inp s-len" aria-label="连上几节" style="width:80px;flex:0 0 80px">' + lenOpts + '</select>' +
    '<input class="inp s-room" style="flex:1;min-width:90px" value="' + esc(s.room || '') + '" placeholder="教室">' +
    '<button type="button" class="icon-btn s-del" style="width:28px;height:28px;flex:0 0 28px">' + ic('trash') + '</button>' +
    weekRuleHTML(s.weeks || '1-18') + '</div>';
}
function bindSess(m) {
  $$('#cfSess .s-del', m).forEach(b => b.onclick = () => b.closest('.sess-row').remove());
  bindWeekRules(m);
}

function editCourse(c, preset, presetWeek) {
  const isNew = !c;
  const full = '1-' + (S.settings.totalWeeks - 2);
  const cur = c || {
    id: uid('c'), name: '', teacher: '', platform: '', url: '',
    color: PALETTE[S.courses.length % PALETTE.length], credits: '', note: '',
    sessions: [preset
      ? { day: preset.day, start: preset.start, len: preset.len, weeks: preset.weeks, room: '' }
      : { day: 1, start: 1, len: 2, weeks: full, room: '' }]
  };
  const sessRows = (cur.sessions || []).map(sessRowHTML).join('');

  const m = openModal(isNew ? '新增课程' : '编辑课程',
    '<div class="field"><label>课程名称</label>' +
      '<input class="inp" id="cfName" placeholder="例如：数据结构" value="' + esc(cur.name) + '"></div>' +
    '<div class="f-row">' +
      '<div class="field"><label>授课老师</label><input class="inp" id="cfTeacher" value="' + esc(cur.teacher) + '"></div>' +
      '<div class="field"><label>学分</label><input class="inp" id="cfCredits" placeholder="选填" value="' + esc(cur.credits) + '"></div>' +
    '</div>' +
    '<div class="f-row">' +
      '<div class="field"><label>所属平台</label><select class="inp" id="cfPlat"><option value="">（未指定）</option>' +
        PLATFORMS.map(p => '<option value="' + p.key + '"' + (cur.platform === p.key ? ' selected' : '') + '>' + esc(p.name) + '</option>').join('') +
        '</select></div>' +
      '<div class="field"><label>课程主页链接</label><input class="inp" id="cfUrl" placeholder="填了以后可一键跳转" value="' + esc(cur.url) + '"></div>' +
    '</div>' +
    '<div class="field"><label>颜色标记</label><div style="display:flex;gap:7px;flex-wrap:wrap" id="cfColors">' +
      PALETTE.map(p => '<button type="button" data-color="' + p + '" style="width:27px;height:27px;border-radius:8px;border:2px solid ' +
        (cur.color === p ? 'var(--text)' : 'transparent') + ';background:' + p + '"></button>').join('') +
    '</div></div>' +
    '<div class="field"><div style="display:flex;align-items:center;margin-bottom:6px">' +
      '<label style="margin:0;flex:1">上课时间安排</label>' +
      '<button type="button" class="btn btn-xs" id="cfAddSess">' + ic('plus') + '添加时段</button></div>' +
      '<div id="cfSess">' + sessRows + '</div>' +
      '<div class="hint">周次写法：<b>1-18</b> 全周 · <b>1-16单</b> 单周 · <b>2-16双</b> 双周 · <b>1-8,10-16</b> 指定周（默认 ' + full + '）</div>' +
    '</div>' +
    '<div class="field"><label>备注</label><textarea class="inp" id="cfNote" placeholder="考试形式、作业要求、任课老师联系方式等">' + esc(cur.note || '') + '</textarea></div>',
    '<button class="btn" data-close>取消</button><button class="btn btn-primary" id="cfSave">' + (isNew ? '创建课程' : '保存') + '</button>',
    { wide: true });

  let color = cur.color;
  $$('#cfColors [data-color]', m).forEach(b => b.onclick = () => {
    color = b.dataset.color;
    $$('#cfColors [data-color]', m).forEach(x => x.style.borderColor = 'transparent');
    b.style.borderColor = 'var(--text)';
  });
  $('#cfAddSess', m).onclick = () => {
    const box = $('#cfSess', m);
    box.insertAdjacentHTML('beforeend', sessRowHTML({ day: 1, start: 1, len: 2, weeks: full, room: '' }, box.children.length));
    bindSess(m);
  };
  bindSess(m);
  $('[data-close]', m).onclick = closeModal;
  $('#cfSave', m).onclick = () => {
    const name = $('#cfName', m).value.trim();
    if (!name) { toast('请填写课程名称', 'warn'); return; }
    const sessions = $$('#cfSess .sess-row', m).map(r => ({
      day: +$('.s-day', r).value,
      start: +$('.s-start', r).value,
      len: +$('.s-len', r).value,
      weeks: weeksFromRule(r) || full,
      room: $('.s-room', r).value.trim()
    })).filter(s => s.day && s.start);
    if (sessions.some(s => s.start + s.len - 1 > sections().length || !validSessionWeeks(s.weeks, S.settings.totalWeeks))) {
      toast('请检查节次和周次：起止周不能倒置或超出学期，单双周内至少有一周', 'warn'); return;
    }
    const data = {
      name: name,
      teacher: $('#cfTeacher', m).value.trim(),
      credits: $('#cfCredits', m).value.trim(),
      platform: $('#cfPlat', m).value,
      url: $('#cfUrl', m).value.trim(),
      color: color,
      note: $('#cfNote', m).value.trim(),
      sessions: sessions
    };
    if (isNew) {
      S.courses.push(normCourse(Object.assign({ id: cur.id }, data)));
      toast('已创建课程：' + name, 'ok');
    } else {
      Object.assign(c, data);
      normCourse(c);
      toast('已保存', 'ok');
    }
    if (presetWeek != null) UI.week = presetWeek;
    save(); closeModal(); render();
  };
}

/* ==================== 课程详情 ==================== */
function openCourse(id) {
  const c = S.courses.find(x => x.id === id);
  if (!c) return;
  const msgs = S.messages.filter(m => m.courseId === id || m.course === c.name)
    .sort((a, b) => (parseD(b.time) || 0) - (parseD(a.time) || 0));
  const todos = S.todos.filter(t => t.courseId === id || t.course === c.name);
  const p = PLAT[c.platform];
  const sess = (c.sessions || []).map(s =>
    '<div class="row"><div class="row-main"><div class="row-title">周' + WD[s.day - 1] + ' 第 ' + s.start + '-' + (s.start + s.len - 1) + ' 节</div>' +
    '<div class="row-meta"><span>' + esc(s.weeks || '全周') + '</span>' + (s.room ? '<span>' + esc(s.room) + '</span>' : '') + '</div></div></div>').join('');

  openModal(c.name,
    '<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap">' +
      '<span class="badge" style="background:' + hexA(c.color, 0.14) + ';color:' + c.color + '"><i class="dot" style="background:' + c.color + '"></i>' + esc(c.teacher || '未填老师') + '</span>' +
      (c.credits ? '<span class="badge b-p3">' + esc(c.credits) + ' 学分</span>' : '') +
      (p ? '<span class="badge" style="background:' + hexA(p.color, 0.14) + ';color:' + p.color + '"><i class="dot" style="background:' + p.color + '"></i>' + esc(p.name) + '</span>' : '') +
      (c.url ? '<a class="btn btn-xs btn-primary" href="' + esc(c.url) + '" target="_blank" rel="noopener">进入课程 ' + ic('ext') + '</a>' : '') +
    '</div>' +
    courseDetailHTML(c) +
    '<div class="sec-title">上课时间</div>' +
    (sess || '<div class="dim" style="font-size:12.5px">未排课</div>') +
    (c.note ? '<div class="sec-title">备注</div><div style="font-size:13px;color:var(--text-2);white-space:pre-wrap">' + esc(c.note) + '</div>' : '') +
    '<div class="sec-title">待办 · ' + todos.filter(t => !t.done).length + ' 项未完成</div>' +
    (todos.length ? todos.map(todoHTML).join('') : '<div class="dim" style="font-size:12.5px">暂无待办</div>') +
    '<div class="sec-title">相关消息 · ' + msgs.length + ' 条</div>' +
    (msgs.length ? msgs.slice(0, 8).map(mm => msgHTML(mm, true)).join('') : '<div class="dim" style="font-size:12.5px">暂无同步的消息</div>'),
    '<button class="btn" data-close>关闭</button>' +
    '<button class="btn" id="ocAddTodo">' + ic('plus') + '加待办</button>' +
    '<button class="btn btn-primary" id="ocEdit">' + ic('pencil') + '编辑课程</button>',
    { wide: true });

  const m = modalStack[modalStack.length - 1];
  $('[data-close]', m).onclick = closeModal;
  $('#ocEdit', m).onclick = () => { closeModal(); editCourse(c); };
  $('#ocAddTodo', m).onclick = () => {
    closeModal();
    editTodo(normTodo({ courseId: c.id, course: c.name, title: c.name + '：', priority: 2, due: defaultDue() }));
  };
  $$('[data-toggle]', m).forEach(el => el.onclick = e => {
    e.stopPropagation();
    const t = S.todos.find(x => x.id === el.dataset.toggle);
    if (!t) return;
    t.done = !t.done; t.doneAt = t.done ? new Date().toISOString() : null;
    save(); closeModal(); render();
  });
  $$('.msg', m).forEach(el => el.onclick = () => {
    const mm = S.messages.find(x => x.id === el.dataset.mid);
    if (mm && !mm.read) { mm.read = true; save(); }
  });
}
