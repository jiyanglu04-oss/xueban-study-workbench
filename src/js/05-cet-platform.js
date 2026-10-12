/* ============================================================
   学伴 · 05 四六级备考 & 平台入口
   ============================================================ */

function cetDailyDone(dateStr) {
  const r = S.cet.daily[dateStr] || {};
  return Object.values(r).filter(Boolean).length;
}
function cetStreak() {
  let n = 0;
  const d = new Date();
  if (cetDailyDone(ymd(d)) === 0) d.setDate(d.getDate() - 1);
  for (let i = 0; i < 400; i++) {
    if (cetDailyDone(ymd(d)) > 0) { n++; d.setDate(d.getDate() - 1); }
    else break;
  }
  return n;
}
function cetProgressPct() {
  const st = parseD((S.cet.startedAt || ymd(new Date())) + 'T00:00:00');
  const ex = parseD(S.cet.examDate + 'T00:00:00');
  if (!st || !ex) return 0;
  const total = Math.max(1, daysBetween(st, ex));
  const done = Math.max(0, daysBetween(st, new Date()));
  return Math.min(100, Math.round(done / total * 100));
}

const CET_PLAN = {
  'CET-4': [
    ['第 1-4 周', '高频词 1500 · 每天 50 个', '吃透听力短对话 + 长对话套路'],
    ['第 5-8 周', '核心词收尾 · 每天 40 个', '仔细阅读精做 2 篇/天，整理同义替换'],
    ['第 9-12 周', '真题词汇查漏', '写作模板成型，翻译每天 1 句'],
    ['第 13 周-考前', '全真模考每周 2 套', '错题复盘，作文背 5 篇范文']
  ],
  'CET-6': [
    ['第 1-4 周', '六级核心词 2000 · 每天 50 个', '听力精听 1 篇/天，跟读记笔记'],
    ['第 5-8 周', '词汇第二轮 + 熟词僻义', '阅读限时训练 15 分钟/篇，正确率 ≥ 70%'],
    ['第 9-12 周', '真题高频词收尾', '写作背 8 篇范文，翻译练中国特色表达'],
    ['第 13 周-考前', '全真模考每周 2 套 + 复盘', '保持手感，作文限时 30 分钟成稿']
  ]
};

function renderCET() {
  const now = new Date();
  const exam = parseD(S.cet.examDate + 'T00:00:00');
  const dExam = exam ? Math.max(0, daysBetween(now, exam)) : 0;
  const today = ymd(now);
  const rec = S.cet.daily[today] || {};
  const doneN = Object.values(rec).filter(Boolean).length;
  const pct = Math.round(doneN / S.cet.tasks.length * 100);
  const streak = cetStreak();
  const totalDays = Object.keys(S.cet.daily).filter(k => cetDailyDone(k) > 0).length;
  const R = 44, C = 2 * Math.PI * R;

  const days = [];
  for (let i = 27; i >= 0; i--) { const d = new Date(); d.setDate(d.getDate() - i); days.push(d); }

  const isExamDay = dExam === 0;
  const weeksLeft = Math.ceil(dExam / 7);

  $('#view').innerHTML =
    finalExamsHTML() +
    '<div class="grid g-dash">' +
      '<div class="card"><div class="card-h">' +
        '<h3>' + ic('target') + ' ' + esc(S.cet.type) + ' 备考看板</h3>' +
        '<div class="sp"><div class="seg" id="cetType">' +
          ['CET-4', 'CET-6'].map(t => '<button data-t="' + t + '" class="' + (S.cet.type === t ? 'on' : '') + '">' + t + '</button>').join('') +
        '</div></div></div>' +
        '<div class="card-b">' +
          '<div style="display:flex;gap:22px;align-items:center;flex-wrap:wrap">' +
            '<div class="ring"><svg width="104" height="104">' +
              '<circle cx="52" cy="52" r="' + R + '" fill="none" stroke="#E6DBC4" stroke-width="9"/>' +
              '<circle cx="52" cy="52" r="' + R + '" fill="none" stroke="#5F7A4A" stroke-width="9" stroke-linecap="round" ' +
              'stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' + (C * (1 - pct / 100)).toFixed(1) + '"/></svg>' +
              '<div class="ring-t"><b>' + pct + '%</b><span>今日进度</span></div></div>' +
            '<div style="flex:1;min-width:210px">' +
              '<div style="display:flex;gap:22px;margin-bottom:14px;flex-wrap:wrap">' +
                '<div><div class="kpi-v">' + dExam + '</div><div class="kpi-k">距考试（天）</div></div>' +
                '<div><div class="kpi-v">' + streak + '</div><div class="kpi-k">连续打卡（天）</div></div>' +
                '<div><div class="kpi-v">' + totalDays + '</div><div class="kpi-k">累计打卡（天）</div></div>' +
              '</div>' +
              '<div class="bar"><i style="width:' + cetProgressPct() + '%"></i></div>' +
              '<div class="hint" style="margin-top:6px">备考周期进度 ' + cetProgressPct() + '%（自 ' + esc(S.cet.startedAt) + ' 起算）· 还剩约 ' + weeksLeft + ' 周</div>' +
              (isExamDay ? '<div class="badge b-p1 mt">考试就在今天，全力以赴！</div>' : '') +
            '</div>' +
          '</div>' +
        '</div></div>' +

      '<div class="card"><div class="card-h"><h3>' + ic('cal') + ' 考试信息</h3></div>' +
        '<div class="card-b">' +
          '<div class="f-row">' +
            '<div class="field"><label>考试日期</label><input class="inp" type="date" id="cetDate" value="' + esc(S.cet.examDate) + '"></div>' +
            '<div class="field"><label>目标分数</label><input class="inp" type="number" id="cetScore" value="' + S.cet.targetScore + '" min="0" max="710"></div>' +
          '</div>' +
          '<div class="field"><label>备考起始日</label><input class="inp" type="date" id="cetStart" value="' + esc(S.cet.startedAt) + '"></div>' +
          '<div class="hint">2026 年下半年四六级笔试通常在 12 月第三个周六（2026-12-19）。<b>请以教务处正式通知为准</b>，通知下来后在这里改一下日期即可。</div>' +
        '</div></div>' +
    '</div>' +

    '<div class="grid g-2 mt">' +
      '<div class="card"><div class="card-h"><h3>' + ic('check') + ' 今日任务</h3>' +
        '<div class="sp"><span class="dim" style="font-size:12px">' + doneN + ' / ' + S.cet.tasks.length + ' 已完成</span></div></div>' +
        '<div class="card-b">' +
          S.cet.tasks.map(t => {
            const on = !!rec[t.id];
            return '<div class="task-line">' +
              '<div class="check' + (on ? ' on' : '') + '" data-cet="' + t.id + '">' + ic('check') + '</div>' +
              '<div class="nm">' + esc(t.name) + '</div>' +
              '<span class="dim" style="font-size:12px">目标 ' + t.goal + ' ' + esc(t.unit) + '</span>' +
              (on ? '<span class="badge b-ok">已完成</span>' : '<span class="badge b-p3">待完成</span>') +
              '</div>';
          }).join('') +
          '<div class="hint" style="margin-top:10px">点左侧方框打卡，数据保存在本机浏览器，换设备请用「设置 → 导出备份」。</div>' +
        '</div></div>' +

      '<div class="card"><div class="card-h"><h3>' + ic('fire') + ' 最近 28 天打卡</h3>' +
        '<div class="sp"><span class="badge b-ok">连续 ' + streak + ' 天</span></div></div>' +
        '<div class="card-b"><div class="streak">' +
          days.map(d => {
            const s = ymd(d);
            const n = cetDailyDone(s);
            const cls = n > 0 ? ' on' : (daysBetween(d, now) < 0 ? ' future' : '');
            return '<div class="day' + cls + (s === today ? ' today' : '') + '" title="' + s + '：' + n + '/' + S.cet.tasks.length + ' 项">' +
              d.getDate() + '</div>';
          }).join('') +
        '</div>' +
        '<div class="hint" style="margin-top:10px">绿色 = 当天有打卡。保持连续，别断节奏——断一天就得从头数。</div>' +
        '</div></div>' +
    '</div>' +

    '<div class="sec-title">' + esc(S.cet.type) + ' 阶段计划</div>' +
    '<div class="grid g-4">' +
      (CET_PLAN[S.cet.type] || CET_PLAN['CET-6']).map((row, i) => {
        const started = parseD(S.cet.startedAt + 'T00:00:00');
        const wkNow = started ? Math.floor(Math.max(0, daysBetween(started, now)) / 7) + 1 : 1;
        const ranges = [[1, 4], [5, 8], [9, 12], [13, 99]];
        const active = wkNow >= ranges[i][0] && wkNow <= ranges[i][1];
        return '<div class="card"' + (active ? ' style="background:var(--primary-w)"' : '') + '>' +
          '<div class="card-b">' +
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:9px">' +
              '<b style="font-size:13.5px">' + esc(row[0]) + '</b>' +
              (active ? '<span class="badge b-info">进行中</span>' : '<span class="badge b-p3">未开始／已过</span>') +
            '</div>' +
            '<div style="font-size:12.5px;color:var(--text-2);line-height:1.7">' +
              '<div>· ' + esc(row[1]) + '</div><div>· ' + esc(row[2]) + '</div>' +
            '</div>' +
          '</div></div>';
      }).join('') +
    '</div>';

  $$('[data-cet]').forEach(el => el.onclick = () => {
    const id = el.dataset.cet;
    S.cet.daily[today] = S.cet.daily[today] || {};
    S.cet.daily[today][id] = !S.cet.daily[today][id];
    if (!Object.values(S.cet.daily[today]).some(Boolean)) delete S.cet.daily[today];
    save();
    renderCET();
    renderSidebar();
    const n = Object.values(S.cet.daily[today] || {}).filter(Boolean).length;
    if (n === S.cet.tasks.length) toast('今日全部任务完成，漂亮！', 'ok');
  });
  $$('#cetType button').forEach(b => b.onclick = () => {
    S.cet.type = b.dataset.t; save(); renderCET(); renderTopbar();
  });
  $('#cetDate').onchange = e => { S.cet.examDate = e.target.value; save(); renderTopbar(); renderCET(); };
  $('#cetScore').onchange = e => { S.cet.targetScore = +e.target.value || 500; save(); renderCET(); };
  $('#cetStart').onchange = e => { S.cet.startedAt = e.target.value; save(); renderCET(); };
  bindFinalExams();
}

/* 期末考试与四六级分别保存，不互相覆盖日期。 */
function finalExamStatus(date, now) {
  const exam = parseD(date + 'T00:00:00');
  if (!exam || ymd(exam) !== date) return { text: '日期无效', days: null, cls: 'b-p1' };
  const days = daysBetween(now || new Date(), exam);
  return { days: days, text: days < 0 ? '已结束 ' + (-days) + ' 天' : (days === 0 ? '今天考试' : '还有 ' + days + ' 天'), cls: days < 0 ? 'b-p3' : (days <= 7 ? 'b-p2' : 'b-info') };
}

function finalExamsHTML() {
  const exams = (S.cet.finalExams || []).slice().sort((a, b) => a.date.localeCompare(b.date));
  const next = exams.find(e => finalExamStatus(e.date).days !== null && finalExamStatus(e.date).days >= 0);
  const count = next ? finalExamStatus(next.date) : null;
  return '<div class="card mb final-exams"><div class="card-h"><h3>' + ic('cal') + ' 期末考试倒计时</h3>' +
    '<div class="sp"><button class="btn btn-sm btn-primary" id="addFinalExam">' + ic('plus') + '添加期末考试</button></div></div>' +
    '<div class="card-b">' + (next ? '<div class="final-next"><div><span class="muted">下一场期末考试</span><h3>' + esc(next.title) + '</h3><span>' + esc(next.date) + (next.room ? ' · ' + esc(next.room) : '') + '</span></div>' +
      '<div><b class="kpi-v">' + count.days + '</b><span> 天' + (count.days === 0 ? ' · 今天考试' : '后考试') + '</span></div></div>' :
      '<p class="hint">' + (exams.length ? '已录入的考试均已结束，可添加下一场考试。' : '添加各科期末日期，或先填写「期末考试开始」日期，倒计时会自动计算。') + '</p>') +
    exams.map(e => {
      const status = finalExamStatus(e.date);
      return '<div class="row"><div class="row-main"><div class="row-title">' + esc(e.title) + '</div><div class="row-meta">' + esc(e.date) +
        (e.room ? ' · ' + esc(e.room) : '') + (e.note ? ' · ' + esc(e.note) : '') + '</div></div>' +
        '<span class="badge ' + status.cls + '">' + status.text + '</span><div class="row-act"><button class="btn btn-xs" data-final-edit="' + esc(e.id) + '">编辑</button>' +
        '<button class="btn btn-xs" data-final-delete="' + esc(e.id) + '">删除</button></div></div>';
    }).join('') + '</div></div>';
}

function bindFinalExams() {
  $('#addFinalExam').onclick = () => editFinalExam(null);
  $$('[data-final-edit]').forEach(b => b.onclick = () => editFinalExam(S.cet.finalExams.find(e => e.id === b.dataset.finalEdit)));
  $$('[data-final-delete]').forEach(b => b.onclick = () => {
    const exam = S.cet.finalExams.find(e => e.id === b.dataset.finalDelete); if (!exam) return;
    confirmBox('删除考试安排', '确定删除「' + esc(exam.title) + '」？不会删除关联课程或待办。', () => {
      S.cet.finalExams = S.cet.finalExams.filter(e => e.id !== exam.id); save(); renderCET();
    }, '删除');
  });
}

function editFinalExam(exam) {
  const current = exam || { id: uid('final'), title: '', date: '', courseId: '', room: '', note: '' };
  const modal = openModal(exam ? '编辑期末考试' : '添加期末考试',
    '<div class="field"><label for="feTitle">考试名称</label><input class="inp" id="feTitle" value="' + esc(current.title) + '" placeholder="例如：高等数学期末 / 期末考试开始"></div>' +
    '<div class="f-row"><div class="field"><label for="feDate">期末考试日期</label><input class="inp" id="feDate" type="date" value="' + esc(current.date) + '"></div>' +
    '<div class="field"><label for="feCourse">关联课程（选填）</label><select class="inp" id="feCourse"><option value="">不关联课程</option>' + myCourses().map(c => '<option value="' + esc(c.id) + '"' + (c.id === current.courseId ? ' selected' : '') + '>' + esc(c.name) + '</option>').join('') + '</select></div></div>' +
    '<div class="field"><label for="feRoom">考试地点（选填）</label><input class="inp" id="feRoom" value="' + esc(current.room) + '"></div>' +
    '<div class="field"><label for="feNote">备注（选填）</label><input class="inp" id="feNote" value="' + esc(current.note) + '"></div>',
    '<button class="btn" data-close>取消</button><button class="btn btn-primary" id="feSave">保存考试日期</button>');
  $('#feCourse', modal).onchange = e => { if (!$('#feTitle', modal).value.trim()) { const course = courseOf(e.target.value); if (course) $('#feTitle', modal).value = course.name + '期末考试'; } };
  $('[data-close]', modal).onclick = closeModal;
  $('#feSave', modal).onclick = () => {
    const title = $('#feTitle', modal).value.trim(), date = $('#feDate', modal).value;
    if (!title || finalExamStatus(date).days === null) { toast('请填写考试名称和有效日期', 'warn'); return; }
    const value = { id: current.id, title: title, date: date, courseId: $('#feCourse', modal).value, room: $('#feRoom', modal).value.trim(), note: $('#feNote', modal).value.trim() };
    if (exam) Object.assign(exam, value); else S.cet.finalExams.push(value);
    save(); closeModal(); renderCET(); toast('期末考试日期已保存', 'ok');
  };
}

/* ==================== 平台入口 ==================== */
function platCard(p, connection) {
  const connected = connection && connection.status === 'connected';
  const failed = connection && connection.status === 'error';
  // needs_login 必须单独成一档。以前它掉进「待连接」，跟「从没同步过」长得一模一样，
  // 于是登录过期后定时同步天天静默跳过，页面上却看不出任何异常。
  const needsLogin = connection && connection.status === 'needs_login';
  const statusText = connected ? '已连接'
    : (failed ? '同步失败'
    : (needsLogin ? '登录已过期'
    : (p.auto ? '待连接' : '手动录入')));
  const statusClass = connected ? 'b-ok' : (failed ? 'b-p1' : (needsLogin ? 'b-p2' : 'b-p3'));

  // 登录态倒计时。能提前算出来，是因为 cookie 的到期时间是平台服务端写死的
  // —— 实测反复同步并不会续期，所以「还剩几天」是个可靠的数字。
  const days = (connection && typeof connection.daysLeft === 'number') ? connection.daysLeft : null;
  const hs = connection && connection.loginStatus;
  let expiryBadge = '';
  let expiryHint = '';
  if (connected && days !== null && hs !== 'session') {
    if (hs === 'expiring') {
      expiryBadge = '<span class="badge b-warn">' + ic('clock') + '登录态剩 ' + days + ' 天</span>';
      expiryHint = '<div class="hint" style="margin-top:6px;color:var(--orange)">' +
        (connection.expiresAt ? connection.expiresAt.slice(0, 10) + ' 到期，' : '') +
        '双击工作台文件夹里的「重新登录.bat」扫码续期即可。到期后自动同步会跳过这个平台。</div>';
    } else if (hs === 'ok') {
      expiryBadge = '<span class="badge b-ok">' + ic('clock') + '登录态剩 ' + days + ' 天</span>';
    }
  }

  return '<div class="card hoverable">' +
    '<div class="plat">' +
      '<div class="plat-ic" style="background:' + p.color + '">' + esc(p.short) + '</div>' +
      '<div class="plat-b"><b>' + esc(p.name) + '</b><p>' + esc(p.desc) + '</p>' +
        '<div style="display:flex;gap:6px;margin-top:9px;flex-wrap:wrap;align-items:center">' +
          (p.home ? '<a class="btn btn-xs btn-primary" href="' + esc(p.home) + '" target="_blank" rel="noopener">打开 ' + ic('ext') + '</a>' : '') +
          (p.work ? '<a class="btn btn-xs" href="' + esc(p.work) + '" target="_blank" rel="noopener">作业</a>' : '') +
          (p.notice ? '<a class="btn btn-xs" href="' + esc(p.notice) + '" target="_blank" rel="noopener">通知</a>' : '') +
          (p.spoc ? '<a class="btn btn-xs" href="' + esc(p.spoc) + '" target="_blank" rel="noopener">校内 SPOC</a>' : '') +
          '<span class="badge ' + statusClass + '">' + statusText + '</span>' +
          expiryBadge +
        '</div>' +
        (connected && connection.lastSync ? '<div class="hint" style="margin-top:6px">最近同步：' + relTime(connection.lastSync) + '</div>' : '') +
        (failed && connection.error ? '<div class="hint" style="margin-top:6px;color:var(--red)">' + esc(connection.error) + '</div>' : '') +
        (needsLogin ? '<div class="hint" style="margin-top:6px;color:var(--orange)">登录态已过期，自动同步会跳过它。双击工作台文件夹里的「重新登录.bat」扫码即可恢复。</div>' : '') +
        expiryHint +
        (p.note ? '<div class="hint" style="margin-top:6px">' + esc(p.note) + '</div>' : '') +
      '</div>' +
    '</div></div>';
}

function renderPlat() {
  const cnt = {};
  const connections = {};
  (S.meta.connections || []).forEach(x => { if (x && x.key) connections[x.key] = x; });
  S.messages.forEach(m => { cnt[m.platform] = (cnt[m.platform] || 0) + 1; });
  const autoN = Object.values(connections).filter(x => x.status === 'connected').length;

  $('#view').innerHTML =
    '<div class="card mb"><div class="card-b" style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
      '<div class="kpi-ic" style="background:#ECE0CC;color:#8B6F47;flex:0 0 42px">' + ic('bolt') + '</div>' +
      '<div style="flex:1;min-width:240px">' +
        '<b style="font-size:13.5px">已连接 ' + autoN + ' 个平台 · 收件箱累计 ' + S.messages.length + ' 条</b>' +
        '<p class="hint" style="margin-top:5px">' + (S.meta.lastSync
          ? '上次同步：' + relTime(S.meta.lastSync) + (S.meta.syncNote ? '（' + esc(S.meta.syncNote) + '）' : '') + '。双击工作台文件夹里的「一键同步数据.bat」即可刷新。'
          : '还没有同步过。双击工作台文件夹里的「一键同步数据.bat」，首次扫码登录后就会自动抓取。') + '</p>' +
      '</div>' +
      '<button class="btn btn-primary btn-sm" id="pSync">' + ic('refresh') + (API.connected ? '立即同步' : '同步方法') + '</button>' +
    '</div></div>' +
    '<div class="grid g-auto">' + PLATFORMS.map(p => {
      const n = cnt[p.key] || 0;
      let html = platCard(p, connections[p.key]);
      if (n) html = html.replace('<p>' + esc(p.desc) + '</p>', '<p>' + esc(p.desc) + ' <b style="color:' + p.color + '">· ' + n + ' 条消息</b></p>');
      return html;
    }).join('') + '</div>' +

    '<div class="sec-title">手动补录消息</div>' +
    '<div class="card"><div class="card-b">' +
      '<p class="hint" style="margin:0 0 14px">微助教和微信 / QQ 群的通知暂时没法自动抓取（微助教绑死微信生态，没有学生网页端）。把消息原文粘进来，' +
      '工作台会生成一条带来源标记的记录，还能在消息中心一键「转待办」。</p>' +
      '<div class="f-row">' +
        '<div class="field"><label>来源平台</label><select class="inp" id="pmPlat">' +
          PLATFORMS.map(p => '<option value="' + p.key + '">' + esc(p.name) + '</option>').join('') + '</select></div>' +
        '<div class="field"><label>关联课程</label><select class="inp" id="pmCourse"><option value="">（不关联）</option>' +
          myCourses().map(c => '<option value="' + c.id + '">' + esc(c.name) + '</option>').join('') + '</select></div>' +
        '<div class="field"><label>类型</label><select class="inp" id="pmKind">' +
          '<option value="notice">公告</option><option value="homework">作业</option>' +
          '<option value="exam">考试</option><option value="signin">签到</option></select></div>' +
      '</div>' +
      '<div class="field"><label>标题</label><input class="inp" id="pmTitle" placeholder="例如：第 7 章作业周五前提交"></div>' +
      '<div class="field"><label>内容</label><textarea class="inp" id="pmBody" placeholder="直接粘贴群里的消息原文"></textarea></div>' +
      '<div class="f-row">' +
        '<div class="field"><label>原文链接（可选）</label><input class="inp" id="pmUrl" placeholder="https://"></div>' +
        '<div class="field"><label>截止时间（可选）</label><input class="inp" type="datetime-local" id="pmDue"></div>' +
      '</div>' +
      '<button class="btn btn-primary" id="pmSave">' + ic('plus') + '录入消息</button>' +
    '</div></div>';

  $('#pSync').onclick = API.connected ? triggerSync : showSyncHelp;
  $('#pmSave').onclick = () => {
    const title = $('#pmTitle').value.trim();
    if (!title) { toast('请填写标题', 'warn'); return; }
    const cid = $('#pmCourse').value;
    const c = S.courses.find(x => x.id === cid);
    S.messages.push(normMsg({
      platform: $('#pmPlat').value, courseId: cid, course: c ? c.name : '',
      title: title, content: $('#pmBody').value.trim(), url: $('#pmUrl').value.trim(),
      kind: $('#pmKind').value, deadline: $('#pmDue').value
    }));
    save(); toast('已录入消息', 'ok'); renderPlat();
  };
}
