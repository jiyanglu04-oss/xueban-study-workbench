/* ==================== 首次使用引导 ====================

   为什么要有这一段
   --------------
   发布包发出去之后，对方电脑上什么都没有：没有课表、没有登录态，
   连 Python 都得现装。以前只能靠他自己在文件夹里翻出一串 .bat 双击，
   很容易卡在第一步就放弃了。

   现在改成：页面一打开就是向导 —— 点一下按钮，扫码窗口自己弹出来；
   扫完自动抓一次，课程和通知直接出现在界面上，全程不用离开浏览器。

   触发条件完全由后端说了算（看 sync/state/onboarded.json 在不在），
   所以老用户永远看不到这个向导，单文件模式也不会弹。
*/

const ONBOARD = {
  need: false,
  step: 'welcome',      // welcome | timetable | login | sync | done
  platforms: [],
  running: null,
  logs: [],
  stats: null,
  timer: null,
  busy: false,
  error: ''
};

const OB_COLOR = { chaoxing: '#3F6BA8', yuketang: '#3F8F6A', icourse163: '#6A5A9C' };
const OB_ICON = { chaoxing: 'book', yuketang: 'bell', icourse163: 'target' };

const OB_STATUS_TXT = {
  ok: '已登录', expiring: '快到期', expired: '已过期',
  session: '已连接', unknown: '未登录', error: '读不到'
};

/* ---------- 和后端对话 ---------- */

async function onboardProbe() {
  if (!API.enabled) return null;
  try {
    const d = await apiRequest('/api/onboarding');
    ONBOARD.platforms = d.platforms || [];
    ONBOARD.running = d.running || null;
    ONBOARD.logs = d.logs || [];
    return d;
  } catch (e) {
    return null;      // 服务没起来就静默降级，不要弹一个点了没反应的向导
  }
}

async function onboardPost(action, payload) {
  return apiRequest('/api/onboarding/' + action, {
    method: 'POST',
    body: JSON.stringify(payload || {})
  });
}

/* ---------- 轮询：这是「扫码好了没」的唯一来源 ---------- */

function onboardStartPoll() {
  if (ONBOARD.timer) return;
  ONBOARD.timer = setInterval(onboardPoll, 1500);
}

function onboardStopPoll() {
  if (ONBOARD.timer) {
    clearInterval(ONBOARD.timer);
    ONBOARD.timer = null;
  }
}

async function onboardPoll() {
  if (ONBOARD.busy || !API.enabled) return;
  ONBOARD.busy = true;
  try {
    const d = await apiRequest('/api/onboarding');
    const before = ONBOARD.running;
    ONBOARD.platforms = d.platforms || [];
    ONBOARD.logs = d.logs || [];
    ONBOARD.running = d.running || null;

    if (ONBOARD.step === 'login') onboardPaintPlatforms();
    if (ONBOARD.step === 'sync') onboardPaintLog();

    // 后台任务从「跑着」变成「停了」——这才是完成信号，不能凭日志猜
    if (before && !ONBOARD.running) {
      if (before.stage === 'login') {
        const p = ONBOARD.platforms.find(x => x.key === before.platform);
        if (p && p.loggedIn) toast(p.label + ' 登录成功', 'ok');
        else toast((p ? p.label : '登录') + ' 这次没完成，可以再试一次', 'warn');
      } else if (before.stage === 'sync' && ONBOARD.step === 'sync') {
        await onboardFinishSync();
      }
    }

    // 从登录步骤点了「开始抓取」之后，跟着后端一起切到抓取进度页
    if (ONBOARD.running && ONBOARD.running.stage === 'sync' && ONBOARD.step === 'login') {
      ONBOARD.step = 'sync';
      onboardRender();
    }
  } catch (e) { /* 静默：轮询失败不该打扰用户 */ }
  finally { ONBOARD.busy = false; }
}

/* ---------- 各步骤的渲染 ---------- */

function onboardShell(stepIndex, bodyHTML, footHTML) {
  const steps = ['欢迎', '课表', '登录', '抓取', '完成'];
  const bar = steps.map((t, i) => {
    const cls = i < stepIndex ? 'done' : (i === stepIndex ? 'now' : '');
    return '<span class="ob-step ' + cls + '"><i>' + (i < stepIndex ? '✓' : (i + 1)) + '</i>' + t + '</span>';
  }).join('<u></u>');

  return '' +
    '<div class="ob-mask" id="obMask">' +
      '<div class="ob-card">' +
        '<div class="ob-head">' +
          '<div class="ob-title">' +
            '<b>学伴</b><span>首次设置向导</span>' +
          '</div>' +
          '<div class="ob-bar">' + bar + '</div>' +
        '</div>' +
        '<div class="ob-body">' + bodyHTML + '</div>' +
        '<div class="ob-foot">' + footHTML + '</div>' +
      '</div>' +
    '</div>';
}

function onboardBodyWelcome() {
  return '' +
    '<h2>欢迎使用学伴</h2>' +
    '<p class="ob-lead">把课表、待办、学习平台的通知和作业收在同一个地方。</p>' +
    '<div class="ob-points">' +
      '<div class="ob-point">' + ic('check') + '<div><b>默认数据保存在本机</b>' +
        '<span>平台同步需要联网；可选小程序云端功能需另行配置。</span></div></div>' +
      '<div class="ob-point">' + ic('user') + '<div><b>用你自己的账号登录</b>' +
        '<span>下面会拉起浏览器窗口，扫码登录一下就行，不会保存你的密码。</span></div></div>' +
      '<div class="ob-point">' + ic('refresh') + '<div><b>按需开启同步与提醒</b>' +
        '<span>完成向导后可在设置中开启定时同步；提醒需要单独配置。</span></div></div>' +
    '</div>' +
    '<p class="ob-hint">整个过程大约 2 分钟。中途想退出也没关系，之后在「设置」里可以重新打开这个向导。</p>';
}

function onboardFootWelcome() {
  return '<button class="btn btn-primary" data-act="toTimetable">开始设置 →</button>';
}

function onboardBodyTimetable() {
  return '<h2>先把你的课表放进来</h2><p class="ob-lead">设置开学日期，上传课表图片。本机识别后，可修改课程的单双周和上课周数。</p>' + timetableImportHTML('obTimetable');
}

function onboardFootTimetable() {
  return '<button class="btn btn-ghost" data-act="skipTimetable">以后再录入</button><button class="btn btn-primary" data-act="saveTimetable">确认课表，下一步 →</button>';
}

function onboardBodyLogin() {
  return '' +
    '<h2>登录你的学习平台</h2>' +
    '<p class="ob-lead">登录哪个就抓哪个。暂时用不上的，直接跳过，以后随时能补。</p>' +
    '<div class="ob-plats" id="obPlats"></div>' +
    '<div class="ob-logbox" id="obLogbox" hidden>' +
      '<div class="ob-logtitle">登录窗口里的进度</div>' +
      '<pre class="ob-log" id="obLog"></pre>' +
    '</div>' +
    '<p class="ob-hint">点「扫码登录」后会弹出一个浏览器窗口，用手机扫码即可。' +
    '登录完窗口会自己关掉，回到这一页继续。</p>';
}

function onboardFootLogin() {
  return '<button class="btn btn-ghost" data-act="skipLogin">都先跳过</button>' +
         '<button class="btn btn-primary" data-act="toSync">登录好了，开始抓数据 →</button>';
}

function onboardPaintPlatforms() {
  const box = $('#obPlats');
  if (!box) return;
  const runningKey = ONBOARD.running && ONBOARD.running.stage === 'login'
    ? ONBOARD.running.platform : '';
  box.innerHTML = ONBOARD.platforms.map(p => {
    const busy = runningKey === p.key;
    const badge = busy ? '登录中…' : (OB_STATUS_TXT[p.status] || p.status);
    const cls = busy ? 'busy' : (p.loggedIn ? 'ok' : 'idle');
    const extra = p.loggedIn && p.daysLeft !== null && p.daysLeft !== undefined
      ? '（还剩 ' + p.daysLeft + ' 天）' : '';
    return '' +
      '<div class="ob-plat ' + cls + '" style="--pc:' + (OB_COLOR[p.key] || '#171717') + '">' +
        '<div class="ob-plat-ic">' + ic(OB_ICON[p.key] || 'link') + '</div>' +
        '<div class="ob-plat-main">' +
          '<b>' + esc(p.label) + '</b>' +
          '<span>' + esc(p.use || '') + '</span>' +
        '</div>' +
        '<div class="ob-plat-side">' +
          '<span class="ob-badge ' + cls + '">' + esc(badge + ' ' + extra) + '</span>' +
          '<button class="btn btn-sm" data-login="' + p.key + '"' + (busy ? ' disabled' : '') + '>' +
            (p.loggedIn ? '重新登录' : '扫码登录') + '</button>' +
        '</div>' +
      '</div>';
  }).join('');

  const logbox = $('#obLogbox');
  if (logbox) logbox.hidden = !runningKey;
  if (runningKey) onboardPaintLog();
}

function onboardBodySync() {
  return '' +
    '<div class="ob-syncing" id="obSyncBox">' +
      '<div class="ob-spin"></div>' +
      '<h2>正在抓取你的课程和通知</h2>' +
      '<p class="ob-lead">第一次通常要 20~40 秒。这一步用的是后台浏览器，不会打扰你。</p>' +
      '<div class="ob-progress"><span id="obBar"></span></div>' +
      '<pre class="ob-log" id="obLog"></pre>' +
    '</div>';
}

function onboardFootSync() {
  return '<button class="btn btn-ghost" data-act="toDone" disabled>先看看界面</button>';
}

function onboardPaintLog() {
  const el = $('#obLog');
  if (!el) return;
  const lines = ONBOARD.logs.slice(-9);
  el.textContent = lines.length ? lines.join('\n') : '正在启动…';
  el.scrollTop = el.scrollHeight;
  const bar = $('#obBar');
  if (bar) bar.style.width = Math.min(88, 12 + ONBOARD.logs.length * 6) + '%';
}

function onboardBodyDone() {
  const s = ONBOARD.stats;
  const line = s
    ? ('已经收到 <b>' + s.msgs + '</b> 条消息、<b>' + s.todos + '</b> 项待办、<b>' + s.courses + '</b> 门课程。')
    : '抓取结束。进去看看有没有新东西。';
  return '' +
    '<div class="ob-done">' + ic('check') + '</div>' +
    '<h2>设置完成</h2>' +
    '<p class="ob-lead">' + line + '</p>' +
    '<div class="ob-points">' +
      '<div class="ob-point">' + ic('cal') + '<div><b>顺便把课表补上</b>' +
        '<span>课表可上传图片识别；之后在「我的课表」里点课程修改单双周、上课周数或教室。</span></div></div>' +
      '<div class="ob-point">' + ic('clock') + '<div><b>学期第一周记得改</b>' +
        '<span>单双周、周次都靠「设置」里的学期开始日期推算。</span></div></div>' +
    '</div>';
}

function onboardFootDone() {
  return '<button class="btn btn-primary" data-act="finish">进入工作台 →</button>';
}

function onboardRender() {
  const idx = { welcome: 0, timetable: 1, login: 2, sync: 3, done: 4 }[ONBOARD.step] || 0;
  let body = '', foot = '';
  if (ONBOARD.step === 'welcome') { body = onboardBodyWelcome(); foot = onboardFootWelcome(); }
  else if (ONBOARD.step === 'timetable') { body = onboardBodyTimetable(); foot = onboardFootTimetable(); }
  else if (ONBOARD.step === 'login') { body = onboardBodyLogin(); foot = onboardFootLogin(); }
  else if (ONBOARD.step === 'sync') { body = onboardBodySync(); foot = onboardFootSync(); }
  else { body = onboardBodyDone(); foot = onboardFootDone(); }

  const old = $('#obMask');
  if (old) old.remove();
  document.body.insertAdjacentHTML('beforeend', onboardShell(idx, body, foot));
  if (ONBOARD.step === 'timetable') {
    $('#obMask .ob-card').classList.add('ob-wide'); bindTimetableImport($('#obTimetable'));
  }

  if (ONBOARD.step === 'login') onboardPaintPlatforms();
  if (ONBOARD.step === 'sync') onboardPaintLog();
  onboardBind();
}

/* ---------- 交互 ---------- */

function onboardBind() {
  const mask = $('#obMask');
  if (!mask) return;
  mask.addEventListener('click', async (e) => {
    const loginBtn = e.target.closest('[data-login]');
    if (loginBtn) { await onboardLogin(loginBtn.getAttribute('data-login')); return; }
    const act = e.target.closest('[data-act]');
    if (!act) return;
    const a = act.getAttribute('data-act');
    if (a === 'toTimetable') { ONBOARD.step = 'timetable'; onboardRender(); }
    else if (a === 'skipTimetable') {
      if (TT_DRAFT.busy) { toast('请等待图片识别完成', 'warn'); return; }
      if (TT_DRAFT.rows.length && !window.confirm('当前课表草稿尚未保存，确定先跳过吗？')) return;
      ONBOARD.step = 'login'; onboardRender(); onboardStartPoll();
    }
    else if (a === 'saveTimetable') {
      if (!commitTimetableDraft($('#obTimetable'))) return;
      ONBOARD.step = 'login'; onboardRender(); onboardStartPoll();
    }
    else if (a === 'skipLogin') { ONBOARD.step = 'sync'; onboardRender(); onboardStartPoll(); await onboardSync(); }
    else if (a === 'toSync') { ONBOARD.step = 'sync'; onboardRender(); onboardStartPoll(); await onboardSync(); }
    else if (a === 'toDone') { ONBOARD.step = 'done'; onboardRender(); }
    else if (a === 'finish') { await onboardFinish(); }
  });
}

async function onboardLogin(key) {
  try {
    const r = await onboardPost('login', { platform: key });
    if (!r.ok) { toast(r.message || '启动失败', 'warn'); return; }
    toast('已打开登录窗口，请用手机扫码', 'ok');
    onboardStartPoll();
  } catch (e) {
    toast('启动登录失败：' + e.message, 'err');
  }
}

async function onboardSync() {
  try {
    const r = await onboardPost('sync', {});
    if (!r.ok) {
      // 环境没装好 / 上一步还在跑 —— 直接把话说清楚，别让用户干等
      ONBOARD.step = 'login';
      onboardRender();
      toast(r.message || '抓取没能启动', 'warn');
      return;
    }
    onboardStartPoll();
  } catch (e) {
    toast('启动抓取失败：' + e.message, 'err');
  }
}

async function onboardFinishSync() {
  ONBOARD.step = 'done';
  ONBOARD.stats = null;
  onboardRender();
  try {
    const d = await apiRequest('/api/state');
    const st = d.state || {};
    ONBOARD.stats = {
      msgs: (st.messages || []).length,
      todos: (st.todos || []).length,
      courses: (st.courses || []).length
    };
    onboardRender();
  } catch (e) { /* 数字拿不到就退化成一句笼统的话 */ }
}

async function onboardFinish() {
  try { await onboardPost('done', {}); } catch (e) { /* 标记失败也不该卡住用户 */ }
  onboardStopPoll();
  const mask = $('#obMask');
  if (mask) mask.remove();
  location.reload();      // 重新走一遍 boot，把抓到的数据读进来
}

/* ---------- 入口 ---------- */

function onboardMaybeStart(d) {
  if (!d || !d.needsOnboarding) return;
  ONBOARD.need = true;
  ONBOARD.step = 'welcome';
  ONBOARD.platforms = d.platforms || [];
  ONBOARD.running = d.running || null;
  ONBOARD.logs = d.logs || [];
  onboardRender();
}

/** 给「设置」页用：想再走一遍向导的时候调它。 */
async function onboardRestart() {
  const d = await onboardProbe();
  if (!d) { toast('后端服务没连上，无法打开向导', 'warn'); return; }
  ONBOARD.step = 'welcome';
  onboardMaybeStart(Object.assign({}, d, { needsOnboarding: true }));
}

})();
/* 收尾说明：整个前端自 01-core.js 起是一个大 IIFE，闭合符放在这里
   （最后加载的模块）。新增模块请排在 06 之后、以本文件为结尾，
   否则代码会掉到闭包外，报 API is not defined。 */
