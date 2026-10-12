/* ============================================================
   学伴 · 06 设置 / 同步 / 提醒 / 启动
   ============================================================ */

/* ==================== 设置页 ==================== */
function renderSet() {
  const campusOpts = Object.keys(CAMPUS_SECTIONS).map(k =>
    '<option value="' + esc(k) + '"' + (S.settings.campus === k ? ' selected' : '') + '>' + esc(k) + '</option>').join('');
  $('#view').innerHTML =
    '<div class="grid g-2">' +

    '<div class="card"><div class="card-h"><h3>' + ic('user') + ' 个人信息</h3></div><div class="card-b">' +
      '<div class="f-row">' +
        '<div class="field"><label>姓名</label><input class="inp" id="stName" value="' + esc(S.profile.name) + '" placeholder="用于打招呼"></div>' +
        '<div class="field"><label>学号</label><input class="inp" id="stSid" value="' + esc(S.profile.sid) + '" placeholder="选填"></div>' +
      '</div>' +
      '<div class="field"><label>学院 / 专业</label><input class="inp" id="stCollege" value="' + esc(S.profile.college) + '" placeholder="选填"></div>' +
      '<div class="hint">' + (API.connected
        ? '个人信息保存在本机 SQLite 数据库中，服务只监听 127.0.0.1，不会上传到互联网。'
        : '当前为离线模式，个人信息只存在本机浏览器中。') + '</div>' +
    '</div></div>' +

    '<div class="card"><div class="card-h"><h3>' + ic('cal') + ' 学期与作息</h3></div><div class="card-b">' +
      '<div class="f-row">' +
        '<div class="field"><label>开学日期（所在周为第 1 周）</label><input class="inp" type="date" id="stTerm" value="' + esc(S.settings.termStart) + '"></div>' +
        '<div class="field"><label>总周数</label><input class="inp" type="number" id="stWeeks" value="' + S.settings.totalWeeks + '" min="1" max="40"></div>' +
      '</div>' +
      '<div class="field"><label>作息模板（按校区）</label><select class="inp" id="stCampus">' + campusOpts + '</select>' +
        '<div class="hint">切换校区会按该校区作息重置节次时间。常见的是 20 周制（1-18 教学周，19-20 考试周）。</div></div>' +
      '<label class="switch' + (S.settings.showWeekend ? ' on' : '') + '" id="stWeekend"><span class="sw"></span>' +
        '<span class="tx"><b>课表显示周末</b><span>开启后周六周日也会出现在课表里</span></span></label>' +
      '<details style="margin-top:10px"><summary style="cursor:pointer;font-size:12.5px;font-weight:600;color:var(--text-2)">' +
        '高级：逐节自定义上课时间</summary>' +
        '<div id="stSecs" style="margin-top:10px;max-height:250px;overflow-y:auto;padding-right:4px">' +
        sections().map((s, i) => '<div style="display:flex;gap:7px;align-items:center;margin-bottom:6px">' +
          '<span class="dim" style="width:36px;font-size:12px">' + (i + 1) + ' 节</span>' +
          '<input class="inp sec-in" data-i="' + i + '" data-k="0" type="time" value="' + s[0] + '" style="flex:1">' +
          '<span class="dim">—</span>' +
          '<input class="inp sec-in" data-i="' + i + '" data-k="1" type="time" value="' + s[1] + '" style="flex:1"></div>').join('') +
        '</div></details>' +
    '</div></div>' +

    '<div class="card"><div class="card-h"><h3>' + ic('bell') + ' 提醒</h3></div><div class="card-b">' +
      '<label class="switch' + (S.settings.notify ? ' on' : '') + '" id="stNotify"><span class="sw"></span>' +
        '<span class="tx"><b>桌面提醒</b><span>待办到期前、上课前弹出系统通知（需保持页面打开）</span></span></label>' +
      '<div class="f-row" style="margin-top:10px">' +
        '<div class="field"><label>提前提醒（分钟）</label><input class="inp" type="number" id="stBefore" value="' + S.settings.remindBeforeMin + '" min="5" max="240"></div>' +
        '<div class="field"><label>&nbsp;</label><button class="btn" id="stTest" style="width:100%">' + ic('bell') + '测试提醒</button></div>' +
      '</div>' +
      '<div class="hint" style="margin-top:8px">' + ic('warn') + ' 浏览器通知仍需保持页面打开；平台数据抓取可由本地服务按设定时间在后台启动。</div>' +
    '</div></div>' +

    '<div class="card"><div class="card-h"><h3>' + ic('refresh') + ' 数据同步与备份</h3></div><div class="card-b">' +
      '<div class="storage-status ' + (API.connected ? 'online' : 'offline') + '">' +
        '<span class="sync-dot ' + (API.connected ? 'ok' : 'bad') + '"></span>' +
        '<div><b>' + (API.connected ? '本机数据库已连接' : '浏览器离线缓存') + '</b>' +
          '<span>' + (API.connected ? '课程、待办、消息和设置会自动写入 data/workbench.sqlite3' : '双击「启动工作台.bat」即可启用 SQLite 持久化') + '</span></div>' +
        (API.connected ? '<button class="btn btn-xs" id="stSaveDb">立即保存</button>' : '') +
      '</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
        '<button class="btn" id="stImport">' + ic('upload') + '导入备份</button>' +
        '<button class="btn" id="stExport">' + ic('download') + '导出备份</button>' +
        '<button class="btn" id="stSyncFile">' + ic('bolt') + '导入同步数据</button>' +
        (API.connected ? '<button class="btn" id="stRunSync">' + ic('refresh') + '立即同步</button>' : '') +
        '<button class="btn btn-primary" id="stHelp">' + ic('refresh') + '同步方法</button>' +
      '</div>' +
      '<div id="schedBox">' + schedBoxHTML() + '</div>' +
      '<div class="sec-title" style="margin:18px 0 8px">统计</div>' +
      '<div style="display:flex;gap:18px;flex-wrap:wrap;font-size:13px">' +
        '<span class="muted" title="本学期在上的课程；平台同步的课程池不计入">课程 <b>' + myCourses().length + '</b></span>' +
        '<span class="muted">待办 <b>' + S.todos.length + '</b></span>' +
        '<span class="muted">消息 <b>' + S.messages.length + '</b></span>' +
        '<span class="muted">打卡 <b>' + Object.keys(S.cet.daily).length + '</b> 天</span>' +
      '</div>' +
      '<div class="sec-title" style="margin:18px 0 8px">危险操作</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
        '<button class="btn btn-danger" id="stClearTodos">清空待办</button>' +
        '<button class="btn btn-danger" id="stClearMsgs">清空消息</button>' +
        '<button class="btn btn-danger" id="stReset">恢复出厂设置</button>' +
      '</div>' +
    '</div></div>' +

    '<div class="card" style="grid-column:1/-1"><div class="card-h"><h3>' + ic('spark') + ' 关于</h3></div><div class="card-b">' +
      '<div style="font-size:13px;color:var(--text-2);line-height:1.85">' +
        '<b style="color:var(--text)">学伴 v1.3.1</b> · 本地优先的全栈应用。可双击单文件离线使用，也可通过本机 API + SQLite 跨浏览器持久化。<br>' +
        '<b style="color:var(--text)">自动同步的平台：</b>超星学习通、雨课堂、中国大学 MOOC。' +
        '教务系统<b>不自动抓</b>（要过统一身份认证 + 短信验证码），课表用「我的课表」手动录入。<br>' +
        '<b style="color:var(--text)">手动录入：</b>微助教（微信生态，无学生网页端）、微信 / QQ 群通知、邮箱。<br>' +
        '<b style="color:var(--text)">通知自动转待办：</b>同步时会读通知正文，识别出「结束时间 / 截止日期」这类信息就建带时间的待办；' +
        '没写时间但命中作业、考试、报名、加群、问卷等关键词的，建一条无时间待办提醒你自己确认（只看最近 21 天的通知，避免历史消息刷屏）。<br>' +
        '<b style="color:var(--text)">数据迁移：</b>换电脑或换浏览器时，先用「导出备份」存下 JSON，在新环境「导入备份」即可完整恢复。' +
      '</div>' +
    '</div></div>' +
    '</div>';

  const bind = (id, fn) => { const el = $(id); if (el) el.onchange = fn; };
  bind('#stName', e => { S.profile.name = e.target.value; save(); renderTopbar(); });
  bind('#stSid', e => { S.profile.sid = e.target.value; save(); });
  bind('#stCollege', e => { S.profile.college = e.target.value; save(); });
  bind('#stTerm', e => {
    const monday = termMonday(e.target.value);
    if (!monday) { toast('请选择有效开学日期', 'warn'); return; }
    S.settings.termStart = monday;
    UI.week = null;
    save(); render();
    toast('已设为第 1 周周一，当前为第 ' + weekOf(new Date()) + ' 周', 'ok');
  });
  bind('#stWeeks', e => { const n = +e.target.value; if (!Number.isInteger(n) || n < 1 || n > 40) { toast('学期总周数必须为 1–40', 'warn'); return; } S.settings.totalWeeks = n; UI.week = null; save(); render(); });
  bind('#stBefore', e => { S.settings.remindBeforeMin = +e.target.value || 30; save(); });

  $('#stCampus').onchange = e => {
    const k = e.target.value;
    S.settings.campus = k;
    if (CAMPUS_SECTIONS[k]) S.settings.sections = JSON.parse(JSON.stringify(CAMPUS_SECTIONS[k]));
    save(); toast('已切换为「' + k + '」作息', 'ok'); renderSet();
  };
  $('#stWeekend').onclick = () => { S.settings.showWeekend = !S.settings.showWeekend; save(); renderSet(); };
  $('#stNotify').onclick = async () => {
    S.settings.notify = !S.settings.notify;
    if (S.settings.notify) {
      const ok = await askNotify();
      if (!ok) {
        S.settings.notify = false;
        toast('浏览器未授权通知，已关闭桌面提醒（页面内提醒仍可用）', 'warn');
      } else {
        toast('桌面提醒已开启', 'ok');
      }
    }
    save(); renderSet();
  };
  $('#stTest').onclick = testNotify;
  const saveDb = $('#stSaveDb');
  if (saveDb) saveDb.onclick = () => pushServerState(true);
  $$('#stSecs .sec-in').forEach(inp => inp.onchange = () => {
    const i = +inp.dataset.i, k = +inp.dataset.k;
    S.settings.sections[i][k] = inp.value;
    save(); toast('已更新第 ' + (i + 1) + ' 节时间', 'ok');
  });

  $('#stExport').onclick = exportJSON;
  $('#stImport').onclick = importJSON;
  $('#stSyncFile').onclick = importSyncFile;
  $('#stHelp').onclick = showSyncHelp;
  const runSync = $('#stRunSync');
  if (runSync) runSync.onclick = triggerSync;
  bindSchedBox();                       // 自动同步卡的开关 / 时间 / 刷新
  if (!SCHED.loaded) refreshScheduleBox();
  $('#stClearTodos').onclick = () => confirmBox('清空待办', '将删除全部待办事项，不可恢复。', () => {
    dismissMany(S.todos.map(t => t.id));   // 记下删除名单，否则同步会把它们全拉回来
    S.todos = []; save(); render(); toast('已清空待办', 'ok');
  }, '清空');
  $('#stClearMsgs').onclick = () => confirmBox('清空消息', '将删除全部消息记录，不可恢复。', () => {
    dismissMany(S.messages.map(m => m.id));
    S.messages = []; save(); render(); toast('已清空消息', 'ok');
  }, '清空');
  $('#stReset').onclick = () => confirmBox('恢复出厂设置', '会清空课程、待办、消息、打卡记录和所有设置，恢复到刚打开时的状态。建议先「导出备份」。', () => {
    try { localStorage.removeItem(LS_KEY); } catch (e) { }
    S = defaultState();
    seedDemo();
    save(); UI.view = 'dash'; UI.week = null;
    render(); toast('已恢复出厂设置', 'ok');
  }, '全部清空');
}

/* ==================== 导入导出 ==================== */
function download(name, text, type) {
  const blob = new Blob([text], { type: type || 'application/json;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 400);
}
function exportJSON() {
  const d = new Date();
  const name = '学伴备份_' + ymd(d) + '_' + pad(d.getHours()) + pad(d.getMinutes()) + '.json';
  download(name, JSON.stringify(S, null, 2));
  toast('已导出备份文件', 'ok');
}
function importJSON() {
  pickFile('.json,application/json', txt => {
    let obj;
    try { obj = JSON.parse(txt); } catch (e) { toast('文件不是合法的 JSON', 'err'); return; }
    if (!obj || typeof obj !== 'object') { toast('文件内容无法识别', 'err'); return; }
    confirmBox('导入备份', '导入后会<b>覆盖</b>当前所有数据。建议先导出一次备份。确定继续吗？', () => {
      S = Object.assign(defaultState(), obj);
      S.settings = Object.assign(defaultState().settings, obj.settings || {});
      S.cet = Object.assign(defaultState().cet, obj.cet || {});
      S.meta = Object.assign(defaultState().meta, obj.meta || {});
      save(); render();
      toast('导入成功', 'ok');
    }, '覆盖导入');
  });
}
function importSyncFile() {
  pickFile('.json,application/json', txt => {
    let obj;
    try { obj = JSON.parse(txt); } catch (e) { toast('文件不是合法的 JSON', 'err'); return; }
    const n = mergePayload(obj, false);
    save(); render();
    toast('同步完成：新增 ' + n.msgs + ' 条消息、' + n.todos + ' 项待办、' + n.courses + ' 门课程', 'ok');
  });
}
function pickFile(accept, cb) {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = accept || '';
  inp.onchange = () => {
    const f = inp.files && inp.files[0];
    if (!f) return;
    const fr = new FileReader();
    fr.onload = () => cb(String(fr.result));
    fr.readAsText(f, 'utf-8');
  };
  inp.click();
}

/* ==================== 同步说明 ==================== */
function showSyncHelp() {
  openModal('数据同步方法',
    '<div style="font-size:13.5px;line-height:1.8;color:var(--text-2)">' +
      '<p style="margin:0 0 14px">平台抓取由同目录下的同步脚本完成。完整模式可以立即运行或按时间自动运行，单文件模式仍可双击脚本。整个流程只需要三步：</p>' +

      '<div style="display:flex;gap:12px;margin-bottom:16px">' +
        '<div style="width:26px;height:26px;border-radius:50%;background:var(--primary);color:#fff;display:grid;place-items:center;flex:0 0 26px;font-weight:700;font-size:13px">1</div>' +
        '<div><b style="color:var(--text)">首次：跟着设置向导走一遍</b><br>页面打开时会自动弹出向导，一步步帮你登录平台、抓第一次数据，全程不用离开浏览器。想重来就点下面的「重看设置向导」。</div>' +
      '</div>' +

      '<div style="display:flex;gap:12px;margin-bottom:16px">' +
        '<div style="width:26px;height:26px;border-radius:50%;background:var(--primary);color:#fff;display:grid;place-items:center;flex:0 0 26px;font-weight:700;font-size:13px">2</div>' +
        '<div><b style="color:var(--text)">双击「一键同步数据.bat」</b><br>会弹出一个浏览器窗口，首次需要你依次扫码登录学习通、雨课堂、MOOC。' +
        '登录状态会被记住，<b>不用每次登录</b>。不过登录态本身有到期日（超星约 30 天、雨课堂约 2 周），' +
        '到期前工作台会显示倒计时并提醒你，那时双击「重新登录.bat」扫一次即可。</div>' +
      '</div>' +

      '<div style="display:flex;gap:12px;margin-bottom:16px">' +
        '<div style="width:26px;height:26px;border-radius:50%;background:var(--green);color:#fff;display:grid;place-items:center;flex:0 0 26px;font-weight:700;font-size:13px">3</div>' +
        '<div><b style="color:var(--text)">脚本自动写回工作台</b><br>抓到的通知、作业、DDL 会合并进这个页面（已读状态、你手改过的内容都不会被覆盖）。' +
        '刷新一下页面就能看到。</div>' +
      '</div>' +

      '<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:14px">' +
        '<b style="color:var(--text);font-size:13px">各平台支持情况</b>' +
        '<table style="width:100%;font-size:12.5px;margin-top:8px;border-collapse:collapse">' +
          '<tr style="color:var(--text-3);text-align:left"><th style="padding:4px 0;font-weight:600">平台</th><th style="font-weight:600">能抓到</th><th style="font-weight:600">方式</th></tr>' +
          '<tr><td style="padding:3px 0">超星学习通</td><td>通知、作业</td><td><span class="badge b-ok">自动</span></td></tr>' +
          '<tr><td style="padding:3px 0">雨课堂</td><td>公告、作业</td><td><span class="badge b-ok">自动</span></td></tr>' +
          '<tr><td style="padding:3px 0">中国大学 MOOC</td><td>课程公告、测验</td><td><span class="badge b-ok">自动</span></td></tr>' +
          '<tr><td style="padding:3px 0">教务系统</td><td>课表图片导入或手动录入</td><td><span class="badge b-p3">不自动抓取</span></td></tr>' +
          '<tr><td style="padding:3px 0">微助教</td><td>—</td><td><span class="badge b-p3">手动录入</span></td></tr>' +
          '<tr><td style="padding:3px 0">微信 / QQ 群</td><td>—</td><td><span class="badge b-p3">手动录入</span></td></tr>' +
        '</table>' +
      '</div>' +

      '<p style="margin:0;font-size:12.5px;color:var(--text-3)">' +
        '也可以点「设置 → 导入同步数据」，手动选择脚本生成的 <code>sync-data.json</code> 文件。' +
        '微助教因为只在微信里运行、没有面向学生的网页端，技术上无法自动抓取；微信群同理。这两类建议随手转发一条“手动录入”。' +
      '</p>' +
    '</div>',
    '<button class="btn" data-close>知道了</button>' +
    '<button class="btn" id="shOnboard">重看设置向导</button>' +
    '<button class="btn btn-primary" id="shImport">立即导入 sync-data.json</button>',
    { wide: true });
  const m = modalStack[modalStack.length - 1];
  $('[data-close]', m).onclick = closeModal;
  $('#shOnboard', m).onclick = () => { closeModal(); onboardRestart(); };
  $('#shImport', m).onclick = () => { closeModal(); importSyncFile(); };
}

/* ==================== 每天自动同步 ====================
   真正的定时执行者是 Windows 计划任务（sync/register_task.ps1），不是这个页面。
   页面只做两件事：把开关/时间下发过去，以及**回读系统里的真实状态**来显示。
   为什么不做成「页面开着时自己定时」：学生不会整天开着这个页面，那样等于没做；
   而且两边同时到点会各起一个浏览器抢同一个 profile。
*/
const SCHED = { loaded: false, enabled: false, mode: 'unknown', times: [], lastRun: null, busy: false, note: '' };

function nextRunText(times) {
  if (!times || !times.length) return '';
  const now = new Date();
  let best = null;
  for (let d = 0; d <= 2; d++) {
    times.forEach(t => {
      const p = String(t).split(':');
      const dt = new Date(now.getFullYear(), now.getMonth(), now.getDate() + d, +p[0] || 0, +p[1] || 0, 0, 0);
      if (dt > now && (!best || dt < best)) best = dt;
    });
  }
  if (!best) return '';
  const hm = pad(best.getHours()) + ':' + pad(best.getMinutes());
  const days = Math.round((new Date(best.getFullYear(), best.getMonth(), best.getDate())
    - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  if (days === 0) return '今天 ' + hm;
  if (days === 1) return '明天 ' + hm;
  return (best.getMonth() + 1) + ' 月 ' + best.getDate() + ' 日 ' + hm;
}

function schedBoxHTML() {
  const m = SCHED.mode;
  let head, sub, tone;
  if (!API.connected) {
    tone = 'offline';
    head = '需要完整模式';
    sub = '双击「启动工作台.bat」打开完整模式后，才能开启系统级定时同步。';
  } else if (m === 'task') {
    tone = 'online';
    head = '已开启 · 由 Windows 计划任务执行';
    sub = '到点自动抓取，<b>不需要开着工作台，也不会弹出浏览器窗口</b>。';
  } else if (m === 'startup') {
    tone = 'online';
    head = '已开启 · 开机自启（备用方案）';
    sub = '这台电脑注册计划任务被系统拦下了，退而求其次放进启动文件夹，每次登录后跑一次。';
  } else if (m === 'none') {
    tone = 'offline';
    head = '未开启';
    sub = '打开右边这个开关，就会交给系统每天定时抓取；错过的时段会在开机后补跑一次。';
  } else {
    tone = 'offline';
    head = SCHED.busy ? '正在处理…' : '状态未知';
    sub = '点下方的「刷新状态」重新读取。';
  }

  const times = (SCHED.times && SCHED.times.length) ? SCHED.times
    : String(S.settings.syncTimes || '08:00,20:00').split(/[,，;；\s]+/).filter(Boolean);
  const nextTxt = (SCHED.enabled && m === 'task') ? nextRunText(times) : '';
  const lastRunTxt = S.meta.lastSync
    ? '上次同步：' + esc(new Date(S.meta.lastSync).toLocaleString('zh-CN'))
      + (S.meta.syncNote ? '（' + esc(S.meta.syncNote) + '）' : '')
    : '上次同步：还没有同步过';

  return '<div class="storage-status ' + tone + '">' +
      '<span class="sync-dot ' + (tone === 'online' ? 'ok' : 'bad') + '"></span>' +
      '<div><b>' + head + '</b><span>' + sub + '</span></div>' +
    '</div>' +
    '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:12px">' +
      '<label class="switch' + (SCHED.enabled ? ' on' : '') + '" id="stAutoSync" style="margin:0;flex:1;min-width:260px">' +
        '<span class="sw"></span>' +
        '<span class="tx"><b>每天自动同步' + (SCHED.enabled && m === 'task' ? ' · ' + times.join(' / ') : '') + '</b>' +
        '<span>登录过期时不会卡住，只在工作台里标注「需要登录」</span></span></label>' +
    '</div>' +
    '<div class="f-row" style="margin-top:12px">' +
      '<div class="field" style="margin:0"><label>执行时间（24 小时制，逗号分隔）</label>' +
        '<input class="inp" id="stSyncTimes" value="' + esc(times.join(',')) + '" placeholder="08:00,20:00" ' +
          (API.connected ? '' : 'disabled') + '></div>' +
      '<div class="field" style="margin:0"><label>&nbsp;</label>' +
        '<button class="btn" id="stSaveTimes" style="width:100%" ' + (API.connected ? '' : 'disabled') + '>' +
        ic('check') + '保存并应用到系统</button></div>' +
    '</div>' +
    '<div class="hint" style="margin-top:8px">' + lastRunTxt +
      (nextTxt ? '<br>下次自动同步：<b>' + nextTxt + '</b>' : '') +
      (SCHED.note ? '<br>' + esc(SCHED.note) : '') + '</div>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
      '<button class="btn btn-xs" id="stSchedRefresh"' + (API.connected ? '' : ' disabled') + '>刷新状态</button>' +
      '<button class="btn btn-xs" id="stSchedGuide">怎么改时间 / 关掉？</button>' +
    '</div>';
}

function bindSchedBox() {
  const sw = $('#stAutoSync');
  if (sw) sw.onclick = () => toggleAutoSync(!SCHED.enabled);
  const saveBtn = $('#stSaveTimes');
  if (saveBtn) saveBtn.onclick = () => {
    const raw = ($('#stSyncTimes').value || '').trim();
    const times = raw.split(/[,，;；\s]+/).filter(Boolean);
    if (!times.length || times.some(t => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(t))) {
      toast('时间格式应为 08:00,20:00', 'warn');
      return;
    }
    if (!SCHED.enabled) {
      S.settings.syncTimes = times.join(',');
      save(); toast('已记住时间；把上面的开关打开后生效', 'ok');
      refreshSchedBoxOnly('已记住时间：' + times.join(' / ') + '。打开开关后生效。');
      return;
    }
    applyAutoSync(true, times);
  };
  const rf = $('#stSchedRefresh');
  if (rf) rf.onclick = () => refreshScheduleBox(true);
  const gd = $('#stSchedGuide');
  if (gd) gd.onclick = showScheduleGuide;
}

/* 不传参数 = 保持当前提示语；传字符串（含空串）= 覆盖它。
   早先写成 if (note) 会让「正在读取…」永远清不掉。 */
function refreshSchedBoxOnly(note) {
  if (typeof note === 'string') SCHED.note = note;
  const box = $('#schedBox');
  if (!box) return;
  box.innerHTML = schedBoxHTML();
  bindSchedBox();
}

function applyScheduleStatus(d) {
  SCHED.mode = d && d.mode ? d.mode : 'none';
  SCHED.enabled = !!(d && d.enabled);
  SCHED.times = (d && Array.isArray(d.times)) ? d.times : [];
  SCHED.lastRun = (d && d.lastRun) || null;
  SCHED.loaded = true;
}

async function refreshScheduleBox(force) {
  if (!API.connected) {
    SCHED.mode = 'none'; SCHED.enabled = false; SCHED.loaded = true;
    refreshSchedBoxOnly();
    return;
  }
  if (SCHED.loaded && !force) { refreshSchedBoxOnly(); return; }
  refreshSchedBoxOnly('正在读取系统里的定时任务…');
  try {
    applyScheduleStatus(await apiRequest('/api/schedule'));
    SCHED.note = '';
  } catch (e) {
    SCHED.mode = 'unknown'; SCHED.loaded = true;
    SCHED.note = '读取系统状态失败，点「刷新状态」再试一次。';
  }
  refreshSchedBoxOnly();
}

async function toggleAutoSync(on) {
  if (!API.connected) { toast('请先通过「启动工作台.bat」打开完整模式', 'warn'); return; }
  const raw = ($('#stSyncTimes') && $('#stSyncTimes').value || '').trim();
  let times = raw.split(/[,，;；\s]+/).filter(Boolean);
  if (!times.length || times.some(t => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(t))) {
    times = String(S.settings.syncTimes || '08:00,20:00').split(/[,，;；\s]+/).filter(Boolean);
  }
  await applyAutoSync(on, times);
}

async function applyAutoSync(enabled, times) {
  if (SCHED.busy) return;
  SCHED.busy = true;
  refreshSchedBoxOnly((enabled ? '正在开启' : '正在关闭') + '系统定时任务…');
  let ok = false, note = '';
  try {
    const d = await apiRequest('/api/schedule', {
      method: 'POST',
      body: JSON.stringify({ enabled: enabled, times: times })
    });
    if (d.status) applyScheduleStatus(d.status);
    ok = !!d.ok;
    if (ok) {
      S.settings.autoSync = !!enabled;
      if (enabled) S.settings.syncTimes = times.join(',');
      save();
      note = enabled
        ? '已交给 Windows 计划任务：每天 ' + times.join(' / ') + ' 自动同步。'
        : '已关闭自动同步，仍然可以随时点「立即同步」。';
    } else {
      note = '操作失败：' + (d.error || '未知错误');
    }
  } catch (e) {
    note = '操作失败：' + (e.message || e);
  }
  SCHED.busy = false;
  SCHED.note = note;
  renderSet();
  toast(note, ok ? 'ok' : 'warn');
}

function showScheduleGuide() {
  openModal('每天自动同步是怎么跑的',
    '<div style="font-size:13px;color:var(--text-2);line-height:1.95">' +
      '<b style="color:var(--text)">谁在执行</b><br>' +
      'Windows 的「任务计划程序」里有一条任务叫 <code>学伴-自动同步</code>，' +
      '每天到你设定的时间就用后台方式（pythonw，无窗口）跑一次 <code>sync/sync.py</code>。' +
      '所以<b>工作台没开着、浏览器关着也照样会同步</b>，抓到的结果直接写进 data/workbench.sqlite3。<br><br>' +
      '<b style="color:var(--text)">错过了怎么办</b><br>' +
      '这条任务开了「错过就补跑」。比如 08:00 时电脑还没开机，9 点开机后它会立刻补跑一次。' +
      '同一时间只允许跑一个，不会两个进程抢浏览器。<br><br>' +
      '<b style="color:var(--text)">登录过期了怎么办</b><br>' +
      '超星 / 雨课堂的登录 cookie 有<b>固定到期时间</b>（平台服务端写死的，反复同步也不会续期），' +
      '所以每隔两三周必然要重新扫一次码。到期前 3 天工作台会变黄提醒，同时电脑右下角弹一次系统通知。' +
      '这时双击一次 <code>重新登录.bat</code>，只给到期的平台弹窗口，扫码完就结束，不重跑抓取。<br>' +
      '（如果错过了提醒，自动同步不会卡住也不弹窗，它会把该平台标成「需要登录」并跳过。）<br><br>' +
      '<b style="color:var(--text)">不想要网页里的开关？</b><br>' +
      '也可以直接双击文件夹里的 <code>注册自动同步.bat</code> / <code>取消自动同步.bat</code>，' +
      '或 <code>自动同步状态.bat</code> 看当前状态。两边的效果一样。<br><br>' +
      '<b style="color:var(--text)">跑失败了去哪里看</b><br>' +
      '<code>sync/logs/sync-日期.log</code> 是每天的运行日志，自动同步的每一步都记在里面。' +
    '</div>',
    '<button class="btn" data-close>知道了</button>', { wide: true });
  const m = modalStack[modalStack.length - 1];
  $('[data-close]', m).onclick = closeModal;
}

async function triggerSync() {
  if (!API.connected) { showSyncHelp(); return; }
  try {
    const data = await apiRequest('/api/sync/run', { method: 'POST' });
    toast(data.message || '同步已启动', 'ok');
  } catch (e) {
    toast(e.message || '无法启动同步', 'warn');
  }
}

/* ==================== 全局搜索 ==================== */
function globalSearch() {
  const body =
    '<div class="field"><input class="inp" id="gsQ" placeholder="搜索课程、待办、消息…" autocomplete="off"></div>' +
    '<div id="gsR"></div>';
  openModal('全局搜索', body, '', { wide: true });
  const m = modalStack[modalStack.length - 1];
  $('[data-close]', m).onclick = closeModal;
  const input = $('#gsQ', m);
  const out = $('#gsR', m);

  const run = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { out.innerHTML = '<div class="hint">输入关键词试试，例如「作业」「高数」「四级」。</div>'; return; }
    const hit = t => String(t == null ? '' : t).toLowerCase().indexOf(q) >= 0;
    const courses = S.courses.filter(c => hit(c.name) || hit(c.teacher));
    const todos = S.todos.filter(t => hit(t.title) || hit(t.note) || hit(t.course));
    const msgs = S.messages.filter(x => hit(x.title) || hit(x.content) || hit(x.course));
    let html = '';
    if (courses.length) {
      html += '<div class="sec-title" style="margin-top:6px">课程 · ' + courses.length + '</div>' +
        courses.slice(0, 6).map(c => '<div class="row" data-r-go="courses"><div class="row-main"><div class="row-title">' +
          '<i style="display:inline-block;width:9px;height:9px;border-radius:3px;background:' + c.color + '"></i> ' +
          esc(c.name) + '</div><div class="row-meta"><span>' + esc(c.teacher || '') + '</span></div></div></div>').join('');
    }
    if (todos.length) {
      html += '<div class="sec-title">待办 · ' + todos.length + '</div>' +
        todos.slice(0, 8).map(t => '<div class="row" data-r-go="todo"><div class="row-main"><div class="row-title">' +
          esc(t.title) + '</div><div class="row-meta"><span class="due ' + dueClass(t.due) + '">' + fmtDue(t.due) + '</span>' +
          (t.course ? '<span>' + esc(t.course) + '</span>' : '') + '</div></div></div>').join('');
    }
    if (msgs.length) {
      html += '<div class="sec-title">消息 · ' + msgs.length + '</div>' +
        msgs.slice(0, 8).map(x => '<div class="row" data-r-go="inbox"><div class="row-main"><div class="row-title">' +
          esc(x.title) + '</div><div class="row-meta"><span>' + esc((PLAT[x.platform] || {}).name || '') + '</span>' +
          '<span>' + relTime(x.time) + '</span></div></div></div>').join('');
    }
    if (!html) html = emptyHTML('search', '没有找到与「' + q + '」相关的内容');
    out.innerHTML = html;
    $$('[data-r-go]', out).forEach(el => el.onclick = () => {
      UI.view = el.dataset.rGo;
      closeModal();
      render();
      window.scrollTo(0, 0);
    });
  };
  input.oninput = run;
  run();
}

/* ==================== 提醒 ==================== */
async function askNotify() {
  if (!('Notification' in window)) return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  try {
    const p = await Notification.requestPermission();
    return p === 'granted';
  } catch (e) { return false; }
}
function pushNotice(title, body) {
  if (S.settings.notify && 'Notification' in window && Notification.permission === 'granted') {
    try { new Notification(title, { body: body, tag: title + body }); } catch (e) { }
  }
  toast(title + '：' + body, 'warn');
}
function testNotify() {
  const now = new Date();
  const w = weekOf(now), wd = weekdayOf(now);
  const t = sessionsOn(w, wd)[0];
  const body = t ? ('下一节：' + t.c.name + ' ' + secTime(t.s.start).start) : ('今天有 ' + openTodos().length + ' 项待办未完成');
  if (S.settings.notify && 'Notification' in window && Notification.permission === 'granted') {
    try { new Notification('学伴 · 提醒测试', { body: body }); } catch (e) { }
    toast('已发送桌面提醒（如果没看到，请检查系统通知权限）', 'ok');
  } else {
    toast('这是一条演示提醒 · ' + body, 'warn');
    if (!S.settings.demo && !('Notification' in window && Notification.permission === 'granted')) {
      toast('想收到桌面弹窗？去 设置 → 打开「桌面提醒」', 'warn');
    }
  }
}

let notifyTimer = null;
function startReminders() {
  if (notifyTimer) clearInterval(notifyTimer);
  notifyTimer = setInterval(checkReminders, 60000);
  setTimeout(checkReminders, 4000);
}
function notifiedAlready(key) {
  if (S.meta.notified.indexOf(key) >= 0) return true;
  S.meta.notified.push(key);
  if (S.meta.notified.length > 300) S.meta.notified = S.meta.notified.slice(-200);
  save();
  return false;
}
function checkReminders() {
  const now = new Date();
  const before = (+S.settings.remindBeforeMin || 30) * 60000;

  // 待办到期提醒
  S.todos.filter(t => !t.done && t.due).forEach(t => {
    const d = parseD(t.due);
    if (!d) return;
    const diff = d - now;
    if (diff > 0 && diff <= before) {
      const key = 'todo-' + t.id + '-' + ymd(now);
      if (!notifiedAlready(key)) pushNotice('待办即将到期', t.title + '（' + Math.round(diff / 60000) + ' 分钟后）');
    } else if (diff <= 0 && diff > -60000) {
      const key = 'todo-over-' + t.id + '-' + ymd(now);
      if (!notifiedAlready(key)) pushNotice('待办已到期', t.title);
    }
  });

  // 上课提醒（提前 20 分钟）
  const w = weekOf(now), wd = weekdayOf(now);
  sessionsOn(w, wd).forEach(x => {
    const t = secTime(x.s.start);
    const hm = t.start.split(':').map(Number);
    const st = new Date(now); st.setHours(hm[0], hm[1], 0, 0);
    const diff = st - now;
    if (diff > 0 && diff <= 20 * 60000) {
      const key = 'class-' + x.c.id + '-' + x.s.start + '-' + ymd(now);
      if (!notifiedAlready(key)) pushNotice('快上课了', x.c.name + ' ' + t.start + (x.s.room ? ' · ' + x.s.room : ''));
    }
  });
}

/* ==================== 渲染调度 ==================== */
function render() {
  renderSidebar();
  renderMobileNav();
  renderTopbar();
  const v = UI.view;
  if (v === 'dash') renderDash();
  else if (v === 'tt') renderTT();
  else if (v === 'todo') renderTodos();
  else if (v === 'inbox') renderInbox();
  else if (v === 'courses') renderCourses();
  else if (v === 'cet') renderCET();
  else if (v === 'plat') renderPlat();
  else if (v === 'set') renderSet();
  else renderDash();
}

/* ==================== 启动 ==================== */
function readSyncPayload() {
  const el = document.getElementById('sync-payload');
  if (!el) return null;
  try {
    const txt = (el.textContent || '').trim();
    if (!txt) return null;
    const obj = JSON.parse(txt);
    if (!obj || typeof obj !== 'object') return null;
    if (!(obj.messages || []).length && !(obj.todos || []).length && !(obj.courses || []).length) return null;
    return obj;
  } catch (e) {
    console.warn('同步数据解析失败', e);
    return null;
  }
}

/* ==================== 后台同步的增量感知 ====================
   自动同步是后台跑的：页面开着不动的时候，数据库可能已经被写进了新通知。
   页面手里还是旧快照，所以回到页面时对一下版本号，变了就把数据读进来并重渲染，
   免得你一直看着几小时前的数据还以为没同步。

   只在**没有待保存改动**时做（saveTimer 是防抖保存的计时器）。
   纯属锦上添花，请求失败就静默放过，不能影响正常使用。 */
async function refreshIfStale() {
  if (!API.enabled || !API.connected || API.saving || saveTimer) return;
  try {
    const data = await apiRequest('/api/state');
    if (!data || !data.revision || data.revision === API.revision) return;
    const m0 = S.messages.length, t0 = S.todos.length;
    if (!applyState(data.state || {})) return;
    API.revision = data.revision;
    try { localStorage.setItem(LS_KEY, JSON.stringify(S)); } catch (e) { }
    render();
    const dm = S.messages.length - m0, dt = S.todos.length - t0;
    if (dm > 0 || dt > 0) {
      const parts = [];
      if (dm > 0) parts.push('新增 ' + dm + ' 条消息');
      if (dt > 0) parts.push('新增 ' + dt + ' 项待办');
      toast('后台同步带来了：' + parts.join(' · '), 'ok');
    }
  } catch (e) { /* 静默 */ }
}

async function boot() {
  let had = load();

  // 通过本地服务打开时，SQLite 是主数据源；服务不可用时自动退回浏览器缓存。
  const serverState = await loadServerState();
  if (serverState) {
    applyState(serverState);
    had = true;
    try { localStorage.setItem(LS_KEY, JSON.stringify(S)); } catch (e) { }
  }

  // 先看同步脚本有没有注入数据
  const payload = readSyncPayload();
  const hasPayload = !!payload && (
    (payload.messages || []).length || (payload.todos || []).length || (payload.courses || []).length);

  // 问一次后端：这是不是「第一次用」（判据是 onboarded.json 在不在）。
  // 发布包发出去时对方一定是第一次 —— 这时就不塞示例数据了，
  // 因为他要看的是自己抓回来的东西，不是一张假课表。
  const onboard = (typeof onboardProbe === 'function') ? await onboardProbe() : null;
  const needOnboard = !!(onboard && onboard.needsOnboarding);

  // 首次使用、而且还没有同步过任何真实数据 → 填一份示例数据方便先看懂界面
  if (!had && !hasPayload && !needOnboard) {
    seedDemo();
    save();
  }

  // 再合并同步数据（一定要放在示例数据之后，否则会被示例数据覆盖掉）
  if (hasPayload) {
    const n = mergePayload(payload, true);
    if (n.msgs || n.todos || n.courses) {
      save();
      setTimeout(() => toast('同步完成：新增 ' + n.msgs + ' 条消息 · ' + n.todos + ' 项待办', 'ok'), 700);
    }
  }

  // 数据库首次启动时，把当前浏览器数据写入 SQLite。
  if (API.connected && !serverState) await pushServerState(false);

  render();
  startReminders();

  // 悬浮操作按钮
  const fabTodo = $('#fabTodo'), fabCourse = $('#fabCourse');
  if (fabTodo) fabTodo.onclick = () => editTodo(null);
  if (fabCourse) fabCourse.onclick = () => editCourse(null);

  // 快捷键
  document.addEventListener('keydown', e => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.key === '/' ) { e.preventDefault(); globalSearch(); }
    else if (e.key.toLowerCase() === 'n' && !e.metaKey && !e.ctrlKey) { e.preventDefault(); editTodo(null); }
    else if (e.key.toLowerCase() === 't' && !e.metaKey && !e.ctrlKey) { e.preventDefault(); editCourse(null); }
    else if (e.key >= '1' && e.key <= '8' && !e.metaKey && !e.ctrlKey) {
      const order = ['dash', 'tt', 'todo', 'inbox', 'courses', 'cet', 'plat', 'set'];
      const k = order[+e.key - 1];
      if (k) { UI.view = k; render(); window.scrollTo(0, 0); }
    }
  });

  // 跨天自动刷新
  let lastDay = ymd(new Date());
  setInterval(() => {
    const d = ymd(new Date());
    if (d !== lastDay) { lastDay = d; render(); }
  }, 30000);

  // 页面重新可见时：刷新相对时间，并看看后台是不是已经同步过新数据了
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    render();
    refreshIfStale();
  });

  // 引导放在最后弹：先把界面渲染好，向导盖在上面，关掉就能直接用。
  // 不能放在最前面 —— 向导要盖在一个已经画好的界面上才不显得像白屏。
  if (needOnboard && typeof onboardMaybeStart === 'function') onboardMaybeStart(onboard);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();

/* ⚠️ 这里刻意不写 })();
   整个前端从 01-core.js 起就是一个大 IIFE，闭合符必须待在**最后加载**的模块里。
   07-onboard.js 排在后面，由它收尾。加新模块时别把顺序搞乱，
   否则新代码会掉到闭包外面 —— 表现为 API is not defined。 */
