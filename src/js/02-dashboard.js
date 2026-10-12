/* ============================================================
   学伴 · 02 总览仪表盘
   ============================================================ */

function kpi(icon, color, bg, value, label, sub) {
  return '<div class="metric"><div class="kpi">' +
    '<div class="kpi-ic" style="background:' + bg + ';color:' + color + '">' + ic(icon) + '</div>' +
    '<div style="min-width:0"><div class="kpi-v">' + value + '</div><div class="kpi-k">' + label + '</div>' +
    (sub ? '<div class="kpi-sub">' + esc(sub) + '</div>' : '') + '</div>' +
    '</div></div>';
}
function emptyHTML(icon, txt) {
  return '<div class="empty">' + ic(icon) + '<div>' + esc(txt) + '</div></div>';
}
function demoBanner() {
  return '<div class="demo-banner mb">' +
    '<div class="card-b" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">' +
    '<span class="badge b-warn">' + ic('spark') + '示例数据</span>' +
    '<span style="font-size:13px;color:var(--text-2);flex:1;min-width:220px">当前显示的是常见课程示例，方便你先看懂界面。清空后就能录入你自己的课程了。</span>' +
    '<button class="btn btn-sm" data-act="cleardemo">清空示例，开始使用</button>' +
    '</div></div>';
}

/* 登录态提醒。
   定时同步是无人值守的：无窗口模式不会弹扫码窗，只会跳过那个平台然后正常退出。
   如果不在这里显式提示，用户的感受就是「数据怎么莫名其妙不更新了」——
   而平台入口页原来把它和「待连接」画成同一个样子，等于没提示。

   分三档，因为紧急程度差很多：
     expired / needs_login —— 已经抓不到数据了，必须处理
     expiring              —— 还剩几天，趁早扫码就好
     unknown               —— 一条凭证都没有，多半是被浏览器清掉了
   登录 cookie 的到期时间是服务端写死的（实测反复同步并不会续期），所以
   「还剩几天」是个可预测的数字 —— 提前说出来，用户才有机会从容处理。 */
function loginAlerts() {
  const out = { expired: [], expiring: [], unknown: [] };
  (S.meta.connections || []).forEach(x => {
    if (!x || !x.key) return;
    const p = PLATFORMS.find(y => y.key === x.key);
    const name = p ? p.name : (x.key || '未知平台');
    const st = x.loginStatus;
    if (x.status === 'needs_login' || st === 'expired') out.expired.push(name);
    else if (st === 'expiring') out.expiring.push(name + '（还剩 ' + x.daysLeft + ' 天）');
    else if (st === 'unknown') out.unknown.push(name);
  });
  return out;
}

function loginBannerItem(badge, icon, title, text, bg, border) {
  return '<div class="demo-banner mb" style="background:' + bg + ';border-color:' + border + '">' +
    '<div class="card-b" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">' +
    '<span class="badge ' + badge + '">' + ic(icon) + esc(title) + '</span>' +
    '<span style="font-size:13px;color:var(--text-2);flex:1;min-width:220px">' + text + '</span>' +
    '<button class="btn btn-sm" data-go="plat">去平台入口</button>' +
    '</div></div>';
}

function loginBanner() {
  const a = loginAlerts();
  let html = '';
  if (a.expired.length) {
    html += loginBannerItem('b-p2', 'warn', '登录已过期',
      esc(a.expired.join('、')) + ' 的登录态失效了，每天两次的自动同步会跳过它。' +
      '双击工作台文件夹里的「重新登录.bat」，扫码一次就能恢复。',
      'var(--orange-w)', 'var(--orange)');
  }
  if (a.unknown.length) {
    html += loginBannerItem('b-p2', 'warn', '找不到登录凭证',
      esc(a.unknown.join('、')) + ' 还没有可用的登录态。' +
      '双击工作台文件夹里的「重新登录.bat」走一次扫码即可。',
      'var(--orange-w)', 'var(--orange)');
  }
  if (a.expiring.length) {
    html += loginBannerItem('b-warn', 'clock', '登录态快到期',
      esc(a.expiring.join('、')) + '。到期后自动同步会自动跳过它 —— ' +
      '双击工作台文件夹里的「重新登录.bat」提前续期，比掉线后再补救省事。',
      '#F8F0D8', 'var(--gold-d)');
  }
  return html;
}

function todayList(list, w, wd) {
  if (!list.length) return emptyHTML('spark', '今天没有排课，自由安排');
  const now = new Date();
  return '<div class="tl">' + list.map(x => {
    const t = secTime(x.s.start);
    const e = secTime(x.s.start + x.s.len - 1).end;
    const sh = t.start.split(':').map(Number);
    const eh = e.split(':').map(Number);
    const st = new Date(); st.setHours(sh[0], sh[1], 0, 0);
    const en = new Date(); en.setHours(eh[0], eh[1], 0, 0);
    const isNow = now >= st && now <= en;
    const isDone = now > en;
    return '<div class="tl-item' + (isNow ? ' now' : '') + (isDone ? ' done' : '') + '">' +
      '<div class="tl-time"><b>' + t.start + '</b><span>' + e + '</span></div>' +
      '<div class="tl-bar" style="background:' + x.c.color + '"></div>' +
      '<div class="tl-body"><b>' + esc(x.c.name) + '</b>' +
      '<span>' + esc(x.s.room || x.c.teacher || '') +
      (x.c.teacher && x.s.room ? ' · ' + esc(x.c.teacher) : '') +
      ' · 第 ' + x.s.start + '-' + (x.s.start + x.s.len - 1) + ' 节' +
      (isNow ? ' · <b style="color:var(--green)">正在上课</b>' : '') + '</span></div>' +
      '</div>';
  }).join('') + '</div>';
}

function renderDash() {
  const now = new Date();
  const w = weekOf(now);
  const wd = weekdayOf(now);
  const today = sessionsOn(w, wd);
  const nextTodo = openTodos().slice()
    .sort((a, b) => (parseD(a.due) || 1e15) - (parseD(b.due) || 1e15)).slice(0, 6);
  const msgs = S.messages.slice()
    .sort((a, b) => (parseD(b.time) || 0) - (parseD(a.time) || 0)).slice(0, 5);
  const exam = parseD(S.cet.examDate + 'T00:00:00');
  const dExam = exam ? Math.max(0, daysBetween(now, exam)) : 0;
  const streak = cetStreak();
  const doneToday = S.cet.daily[ymd(now)] || {};
  const doneN = Object.values(doneToday).filter(Boolean).length;

  const weekDeadlines = openTodos().filter(t => {
    const d = parseD(t.due);
    return d && daysBetween(now, d) <= 7 && daysBetween(now, d) >= -30;
  }).length;

  const days = S.settings.showWeekend ? 7 : 5;
  let weekCourseCount = 0;
  for (let i = 1; i <= days; i++) weekCourseCount += sessionsOn(w, i).length;

  let nextTxt = today.length ? '今天的课已上完' : '今天没课';
  for (const x of today) {
    const e = secTime(x.s.start + x.s.len - 1).end.split(':').map(Number);
    const end = new Date(); end.setHours(e[0], e[1], 0, 0);
    if (end > now) { nextTxt = '下一节 ' + secTime(x.s.start).start + ' ' + x.c.name; break; }
  }

  const html =
    (S.settings.demo ? demoBanner() : '') +
    loginBanner() +
    '<section class="dash-intro"><div><h1>把今天<span>安排好。</span></h1><p>课程、作业与通知，一处掌握。</p></div><div class="dash-stamp">第 ' + w + ' 周 · 星期' + WD[wd - 1] + '</div></section>' +
    '<div class="grid g-4">' +
      kpi('cal', '#8B6F47', '#ECE0CC', today.length, '今日课程', nextTxt) +
      kpi('check', '#B8762B', '#F7E8D1', weekDeadlines, '7 天内 DDL', openTodos().length + ' 项待办进行中') +
      kpi('inbox', '#7D6B8F', '#EEE7F0', unreadMsgs().length, '未读消息', S.messages.length + ' 条消息 · ' + PLATFORMS.length + ' 个来源') +
      kpi('fire', '#5F7A4A', '#E5EBD9', streak, '连续打卡', '今日 ' + doneN + ' / ' + S.cet.tasks.length + ' 项已完成') +
    '</div>' +

    '<div class="sec-title">今日安排</div>' +
    '<div class="grid g-dash">' +
      '<div class="card"><div class="card-h"><h3>' + ic('cal') + ' 今日课程</h3>' +
        '<div class="sp"><span class="dim" style="font-size:12px">第 ' + w + ' 周 星期' + WD[wd - 1] + ' · 共 ' + today.length + ' 节</span>' +
        '<button class="btn btn-sm btn-ghost" data-go="tt">查看课表</button></div></div>' +
        '<div class="card-b">' + todayList(today, w, wd) + '</div></div>' +

      '<div class="card exam-card"><div class="card-h"><h3>' + ic('target') + ' ' + esc(S.cet.type) + ' 倒计时</h3>' +
        '<div class="sp"><button class="btn btn-sm btn-ghost" data-go="cet">备考计划</button></div></div>' +
        '<div class="card-b"><div class="cd">' +
          '<div class="cd-num">' + dExam + '</div>' +
          '<div class="cd-lab">天后考试 · ' + (exam ? (exam.getMonth() + 1) + ' 月 ' + exam.getDate() + ' 日' : '未设置') + '</div>' +
          '<div class="cd-sub">本周共 ' + weekCourseCount + ' 节课 · 目标 ' + S.cet.targetScore + ' 分</div>' +
        '</div>' +
        '<div class="bar" style="margin-top:16px"><i style="width:' + cetProgressPct() + '%"></i></div>' +
        '<div class="hint" style="text-align:center;margin-top:8px">备考周期进度 ' + cetProgressPct() + '% · 已坚持 ' + streak + ' 天</div>' +
        '</div></div>' +
    '</div>' +

    '<div class="grid g-2 mt">' +
      '<div class="card"><div class="card-h"><h3>' + ic('check') + ' 最近待办</h3>' +
        '<div class="sp">' + (overdueTodos().length ? '<span class="badge b-p1">' + overdueTodos().length + ' 项逾期</span>' : '') +
        '<button class="btn btn-sm btn-ghost" data-go="todo">全部</button></div></div>' +
        '<div class="card-b flush">' +
        (nextTodo.length ? nextTodo.map(todoHTML).join('') : emptyHTML('check', '暂无待办，很清爽')) + '</div></div>' +

      '<div class="card"><div class="card-h"><h3>' + ic('inbox') + ' 最新消息</h3>' +
        '<div class="sp"><span class="dim" style="font-size:11.5px">' + unreadMsgs().length + ' 条未读</span>' +
        '<button class="btn btn-sm btn-ghost" data-go="inbox">进入收件箱</button></div></div>' +
        '<div class="card-b flush">' +
        (msgs.length ? msgs.map(m => msgHTML(m, true)).join('') : emptyHTML('inbox', '还没有消息，试试运行同步脚本')) + '</div></div>' +
    '</div>' +

    '<div class="sec-title">常用平台</div>' +
    '<div class="platform-shortcuts">' + PLATFORMS.filter(p => p.home).slice(0, 4).map(p =>
      '<a class="platform-shortcut" href="' + esc(p.home || '#') + '" target="_blank" rel="noopener">' +
        '<span class="plat-ic" style="background:' + p.color + '">' + esc(p.short) + '</span>' +
        '<span><b>' + esc(p.name) + '</b><small>' + esc(p.desc.split('、').slice(0, 2).join('、')) + '</small></span>' +
        ic('ext') + '</a>').join('') + '</div>';

  $('#view').innerHTML = html;
  bindDash();
}

function bindDash() {
  $$('[data-go]').forEach(b => b.onclick = () => { UI.view = b.dataset.go; render(); window.scrollTo(0, 0); });
  $$('[data-act="cleardemo"]').forEach(b => b.onclick = () => {
    confirmBox('清空示例数据', '会删除全部示例课程、待办、消息和打卡记录，然后你就可以录入自己的数据了。', clearAll, '清空并开始');
  });
  bindTodoEvents();
  $$('.msg').forEach(el => el.onclick = () => {
    const m = S.messages.find(x => x.id === el.dataset.mid);
    if (m && !m.read) { m.read = true; save(); render(); }
  });
}

/* ==================== 示例数据 ==================== */
function seedDemo() {
  const P = (n) => PALETTE[n % PALETTE.length];
  const S1 = '1-18';
  S.courses = [
    normCourse({ id: 'demo-c1', name: '高等数学（上）', teacher: '陈老师', platform: 'chaoxing', color: P(0),
      credits: '5', url: 'https://i.chaoxing.com', room: '教学楼 A301',
      sessions: [
        { day: 1, start: 1, len: 2, weeks: S1, room: '教学楼 A301' },
        { day: 3, start: 3, len: 2, weeks: S1, room: '教学楼 A301' },
        { day: 5, start: 5, len: 2, weeks: '1-16单', room: '教学楼 A301' }
      ] }),
    normCourse({ id: 'demo-c2', name: '大学英语（三）', teacher: 'Linda Wang', platform: 'yuketang', color: P(1),
      credits: '3', url: 'https://www.yuketang.cn/web', room: '文科楼 205',
      sessions: [
        { day: 2, start: 3, len: 2, weeks: S1, room: '文科楼 205' },
        { day: 4, start: 3, len: 2, weeks: S1, room: '文科楼 205' }
      ] }),
    normCourse({ id: 'demo-c3', name: '线性代数', teacher: '黄老师', platform: 'chaoxing', color: P(2),
      credits: '3', url: 'https://i.chaoxing.com', room: '教学楼 B104',
      sessions: [
        { day: 2, start: 1, len: 2, weeks: S1, room: '教学楼 B104' },
        { day: 4, start: 1, len: 2, weeks: S1, room: '教学楼 B104' }
      ] }),
    normCourse({ id: 'demo-c4', name: '微观经济学', teacher: '李老师', platform: 'icourse163', color: P(3),
      credits: '3', url: 'https://www.icourse163.org/', room: '经济楼 402',
      sessions: [
        { day: 3, start: 7, len: 2, weeks: S1, room: '经济楼 402' },
        { day: 5, start: 1, len: 2, weeks: S1, room: '经济楼 402' }
      ] }),
    normCourse({ id: 'demo-c5', name: '计算机程序设计', teacher: '张老师', platform: 'chaoxing', color: P(4),
      credits: '4', url: 'https://i.chaoxing.com', room: '实验楼机房 3',
      sessions: [
        { day: 4, start: 7, len: 2, weeks: S1, room: '实验楼机房 3' },
        { day: 5, start: 7, len: 2, weeks: '1-18', room: '实验楼机房 3' }
      ] }),
    normCourse({ id: 'demo-c6', name: '大学体育（三）', teacher: '刘老师', platform: '', color: P(5),
      credits: '1', url: '', room: '田径场',
      sessions: [{ day: 3, start: 5, len: 2, weeks: S1, room: '田径场' }] })
  ];

  const now = new Date();
  const iso = (dayOffset, hh, mm) => {
    const d = new Date(now);
    d.setDate(d.getDate() + dayOffset);
    d.setHours(hh || 9, mm || 0, 0, 0);
    return d.toISOString();
  };
  const due = (dayOffset, hh, mm) => {
    const d = new Date(now);
    d.setDate(d.getDate() + dayOffset);
    d.setHours(hh || 23, mm || 59, 0, 0);
    return ymd(d) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  };

  S.messages = [
    normMsg({ id: 'demo-m1', platform: 'chaoxing', kind: 'homework', course: '高等数学（上）', courseId: 'demo-c1',
      title: '第 5 章 定积分 作业已发布', deadline: due(2),
      content: '同学们好，第五章课后习题 5.1—5.8 请在截止时间前拍照上传，逾期系统自动关闭提交入口。注意书写过程要完整。',
      url: 'https://mooc1-api.chaoxing.com/work/stu-work', time: iso(0, 8, 30) }),
    normMsg({ id: 'demo-m2', platform: 'yuketang', kind: 'notice', course: '大学英语（三）', courseId: 'demo-c2',
      title: '下周三课堂展示分组名单已上传', deadline: due(6),
      content: '本周课前请各位同学预习 Unit 4 的 reading 部分，课件已上传雨课堂。课堂展示每组 8 分钟，名单见附件。',
      url: 'https://www.yuketang.cn/web', time: iso(0, 10, 15) }),
    normMsg({ id: 'demo-m3', platform: 'icourse163', kind: 'homework', course: '微观经济学', courseId: 'demo-c4',
      title: '第 4 周单元测验开放（截止本周日）', deadline: due(4),
      content: '本周单元测验共 15 题，限时 30 分钟，可提交两次取最高分。请在 MOOC 平台「测验与作业」栏目完成。',
      url: 'https://www.icourse163.org/', time: iso(-1, 14, 20) }),
    normMsg({ id: 'demo-m4', platform: 'jw', kind: 'notice', course: '',
      title: '关于 2026-2027 学年第一学期重修报名的通知',
      content: '教务处通知：本学期重修报名将于第 8 周开放，请需要重修的同学关注教务系统通知，逾期不再受理。',
      url: '', time: iso(-1, 16, 40) }),
    normMsg({ id: 'demo-m5', platform: 'chaoxing', kind: 'notice', course: '计算机程序设计', courseId: 'demo-c5',
      title: '实验课改为线上进行的通知', 
      content: '周四实验课因机房检修改为线上进行，请提前在电脑上安装好 Python 3.11 和 VS Code，线上链接届时发在课程群。',
      url: 'https://i.chaoxing.com', time: iso(-2, 9, 5) }),
    normMsg({ id: 'demo-m6', platform: 'yuketang', kind: 'notice', course: '线性代数', courseId: 'demo-c3',
      title: '课件已更新：矩阵的初等变换',
      content: '本次课件补充了 3 道典型例题，建议结合课本 P78-P85 一起复习，下周小测会涉及。',
      url: 'https://www.yuketang.cn/web', time: iso(-3, 20, 10), read: true })
  ];

  S.todos = [
    normTodo({ id: 'demo-t1', title: '高数第五章课后习题 5.1—5.8', courseId: 'demo-c1', course: '高等数学（上）',
      due: due(2), priority: 1, source: 'chaoxing' }),
    normTodo({ id: 'demo-t2', title: '微观经济学第 4 周单元测验', courseId: 'demo-c4', course: '微观经济学',
      due: due(4), priority: 1, source: 'icourse163' }),
    normTodo({ id: 'demo-t3', title: '英语课堂展示 PPT 初稿', courseId: 'demo-c2', course: '大学英语（三）',
      due: due(5), priority: 2, source: 'yuketang' }),
    normTodo({ id: 'demo-t4', title: '复习线性代数矩阵初等变换', courseId: 'demo-c3', course: '线性代数',
      due: due(1), priority: 2, source: 'manual' }),
    normTodo({ id: 'demo-t5', title: 'Python 实验二：循环与函数', courseId: 'demo-c5', course: '计算机程序设计',
      due: due(-1), priority: 1, source: 'chaoxing' }),
    normTodo({ id: 'demo-t6', title: '背诵四级核心词汇 Unit 1-3', course: '',
      due: due(3), priority: 2, source: 'manual' })
  ];

  // 最近 11 天的备考打卡记录
  const ids = ['vocab', 'listen', 'read', 'write'];
  for (let i = 11; i >= 0; i--) {
    if (i === 4) continue; // 制造一天断卡
    const d = new Date(); d.setDate(d.getDate() - i);
    const rec = {};
    ids.forEach((k, idx) => { rec[k] = i > 2 ? true : idx < 2; });
    S.cet.daily[ymd(d)] = rec;
  }
  S.settings.demo = true;
  S.settings.firstRun = false;
}

function clearAll() {
  const keepProfile = JSON.parse(JSON.stringify(S.profile));
  S = defaultState();
  S.profile = keepProfile;
  save();
  render();
  toast('已清空，开始录入你自己的课程吧', 'ok');
}
