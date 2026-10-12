/* ============================================================
   学伴 · 01 核心层
   常量 / 工具函数 / 状态管理 / 同步数据合并 / 弹窗 / 侧栏 / 顶栏
   ============================================================ */
(function () {
'use strict';

/* ==================== 常量 ==================== */

const LS_KEY = 'lwb_v1';
const WD = ['一', '二', '三', '四', '五', '六', '日'];

/* 默认作息（20 周制：1-18 教学周，19-20 考试周），可在「设置」里改 */
const CAMPUS_SECTIONS = {
  '校本部 / 珠海': [
    ['08:00', '08:45'], ['08:55', '09:40'], ['10:00', '10:45'], ['10:55', '11:40'],
    ['12:40', '13:25'], ['13:35', '14:20'],
    ['14:30', '15:15'], ['15:25', '16:10'],
    ['16:20', '17:05'], ['17:15', '18:00'],
    ['19:00', '19:45'], ['19:55', '20:40'], ['20:50', '21:35']
  ],
  '番禺 / 华文': [
    ['08:30', '09:15'], ['09:25', '10:10'], ['10:30', '11:15'], ['11:25', '12:10'],
    ['13:10', '13:55'], ['14:05', '14:50'],
    ['15:00', '15:45'], ['15:55', '16:40'],
    ['16:50', '17:35'], ['17:45', '18:30'],
    ['19:30', '20:15'], ['20:25', '21:10'], ['21:20', '22:05']
  ],
  '深圳校区': [
    ['08:00', '08:45'], ['08:50', '09:35'], ['09:50', '10:35'], ['10:40', '11:25'],
    ['13:30', '14:15'], ['14:20', '15:05'],
    ['15:20', '16:05'], ['16:10', '16:55'],
    ['17:10', '17:55'], ['18:00', '18:45'],
    ['19:00', '19:45'], ['19:50', '20:35'], ['20:40', '21:25']
  ]
};

const PLATFORMS = [
  { key: 'chaoxing', name: '超星学习通', short: '学', color: '#3F6BA8', auto: true,
    home: 'https://i.chaoxing.com',
    login: 'https://passport2.chaoxing.com/login?fid=&newversion=true&refer=https%3A%2F%2Fi.chaoxing.com',
    notice: 'https://notice.chaoxing.com/pc/notice/noticeList',
    work: 'https://mooc1-api.chaoxing.com/work/stu-work',
    desc: '课程通知、作业、签到、章节任务点' },
  { key: 'yuketang', name: '雨课堂', short: '雨', color: '#3F8F6A', auto: true,
    home: 'https://www.yuketang.cn/web', login: 'https://www.yuketang.cn/web',
    desc: '课堂公告、课后作业、课件与回放' },
  { key: 'icourse163', name: '中国大学 MOOC', short: 'M', color: '#6A5A9C', auto: true,
    home: 'https://www.icourse163.org/',
    spoc: 'https://www.icourse163.org/spoc/schoolcloud/index.htm',
    desc: '校内 SPOC 与慕课作业、测验、公告' },
  { key: 'jw', name: '教务系统', short: '教', color: '#B0453F', auto: false,
    home: '', login: '',
    desc: '课表、考试安排、成绩、教务通知',
    note: '各校教务系统不同，课表建议直接在「我的课表」里录入' },
  { key: 'weizhujiao', name: '微助教', short: '微', color: '#C2722F', auto: false,
    home: 'https://www.teachermate.com.cn/',
    desc: '签到、答题、课堂互动', note: '需微信生态，暂用手动转发' },
  { key: 'wechat', name: '微信 / QQ 群', short: '群', color: '#6B6A5F', auto: false,
    home: '', desc: '班级群、课程群里的临时通知', note: '复制消息 → 工作台手动录入' },
  { key: 'mail', name: '邮箱', short: '邮', color: '#3D7A8A', auto: false,
    home: 'https://mail.qq.com', desc: '老师邮件、学校公文' }
];

/* 课程色盘：大地色系，在暖米纸底上做淡色块 + 深色左条都清楚 */
const PALETTE = ['#8B6F47', '#6B7F4A', '#A2543C', '#7D6B8F', '#4D6B75', '#B8912A',
                 '#96566F', '#5F7A6B', '#A8763C', '#6A6A5C'];

const ICONS = {
  home: '<path d="M3 10.6 12 3.2l9 7.4"/><path d="M5.5 9.6V20.5h13V9.6"/><path d="M9.8 20.5v-5.4h4.4v5.4"/>',
  cal: '<rect x="3" y="4.6" width="18" height="16.4" rx="2.6"/><path d="M3 9.6h18M8 3v3.4M16 3v3.4"/>',
  check: '<path d="M9 11.4l2.2 2.2 4.4-4.6"/><rect x="3.2" y="4.2" width="17.6" height="16.6" rx="3"/>',
  bell: '<path d="M18 8.6a6 6 0 1 0-12 0c0 6-2.4 7.6-2.4 7.6h16.8S18 14.6 18 8.6"/><path d="M13.7 20a2 2 0 0 1-3.4 0"/>',
  book: '<path d="M4 4.6A2.6 2.6 0 0 1 6.6 2H20v17.4H6.6A2.6 2.6 0 0 0 4 22z"/><path d="M4 19.4h16"/>',
  grid: '<rect x="3.2" y="3.2" width="7.6" height="7.6" rx="2"/><rect x="13.2" y="3.2" width="7.6" height="7.6" rx="2"/><rect x="3.2" y="13.2" width="7.6" height="7.6" rx="2"/><rect x="13.2" y="13.2" width="7.6" height="7.6" rx="2"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  link: '<path d="M10.6 13.4a4 4 0 0 0 5.7 0l3-3a4 4 0 1 0-5.7-5.7l-1.7 1.7"/><path d="M13.4 10.6a4 4 0 0 0-5.7 0l-3 3a4 4 0 1 0 5.7 5.7l1.7-1.7"/>',
  cog: '<circle cx="12" cy="12" r="3.2"/><path d="M19.5 12a7.5 7.5 0 0 0-.1-1.2l2-1.5-2-3.5-2.4 1a7.5 7.5 0 0 0-2-1.2L14.6 3h-4l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.4-1-2 3.5 2 1.5a7.5 7.5 0 0 0 0 2.4l-2 1.5 2 3.5 2.4-1a7.5 7.5 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.4 1 2-3.5-2-1.5c.06-.4.1-.8.1-1.2z"/>',
  plus: '<path d="M12 5.2v13.6M5.2 12h13.6"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  pencil: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  trash: '<path d="M3 6h18M8 6V4.2A1.2 1.2 0 0 1 9.2 3h5.6A1.2 1.2 0 0 1 16 4.2V6"/><path d="M18.6 6 18 20.2a1.8 1.8 0 0 1-1.8 1.8H7.8A1.8 1.8 0 0 1 6 20.2L5.4 6"/>',
  ext: '<path d="M18 13.6V20a1.6 1.6 0 0 1-1.6 1.6H4A1.6 1.6 0 0 1 2.4 20V8a1.6 1.6 0 0 1 1.6-1.6h6.4"/><path d="M14.4 2.4H21.6V9.6"/><path d="M10.4 13.6 21.6 2.4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.4l3.4 2"/>',
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M4.4 21a7.6 7.6 0 0 1 15.2 0"/>',
  refresh: '<path d="M20.4 11a8.4 8.4 0 1 0-.6 4.4"/><path d="M20.4 5.4V11H15"/>',
  download: '<path d="M12 3.4v12.2"/><path d="M7.4 11.2 12 15.8l4.6-4.6"/><path d="M4 20.4h16"/>',
  upload: '<path d="M12 15.8V3.6"/><path d="M7.4 8.2 12 3.6l4.6 4.6"/><path d="M4 20.4h16"/>',
  warn: '<path d="M12 3.4 22 20.4H2z"/><path d="M12 10v4.4M12 17.6v.1"/>',
  fire: '<path d="M12 22c4 0 6.6-2.6 6.6-6.2 0-4.6-4.4-6-5.4-11.8-2 1.8-3 3.6-3 5.6 0 1.6-1.4 2-2.2.8-.6 1.2-.6 2.4-.6 3.4C7.4 17.6 8.6 22 12 22z"/>',
  spark: '<path d="M12 3.4 13.6 9 19 10.6 13.6 12.2 12 17.8 10.4 12.2 5 10.6 10.4 9z"/><path d="M18.6 16.4l.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7z"/>',
  search: '<circle cx="10.6" cy="10.6" r="6.6"/><path d="M20 20l-4.7-4.7"/>',
  inbox: '<path d="M21.6 12.4h-5.2l-1.4 2.6h-6l-1.4-2.6H2.4"/><path d="M5.2 4.2h13.6l2.8 8.2v6a2 2 0 0 1-2 2H4.4a2 2 0 0 1-2-2v-6z"/>',
  file: '<path d="M14 2.4H7.2A1.8 1.8 0 0 0 5.4 4.2v15.6a1.8 1.8 0 0 0 1.8 1.8h10.8a1.8 1.8 0 0 0 1.8-1.8V7.8z"/><path d="M14 2.4v5.4h5.8"/>',
  bolt: '<path d="M13.4 2.4 4.8 13.4h6.4l-.6 8.2 8.6-11h-6.4z"/>'
};
function ic(n, c) {
  return '<svg class="i ' + (c || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[n] || '') + '</svg>';
}

/* ==================== 工具 ==================== */
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.prototype.slice.call((r || document).querySelectorAll(s));
const pad = n => String(n).padStart(2, '0');
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ymd = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
function parseD(s) {
  if (!s) return null;
  const d = new Date(String(s).replace(' ', 'T'));
  return isNaN(d.getTime()) ? null : d;
}
function uid(p) { return (p || 'id') + '-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
function weekdayOf(d) { const w = d.getDay(); return w === 0 ? 7 : w; }
function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
function daysBetween(a, b) {
  const A = new Date(a); A.setHours(0, 0, 0, 0);
  const B = new Date(b); B.setHours(0, 0, 0, 0);
  return Math.round((B - A) / 86400000);
}
function fmtDue(s) {
  const d = parseD(s); if (!d) return '无截止';
  const diff = d - new Date();
  const dd = daysBetween(new Date(), d);
  const hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
  if (diff < 0) return dd === 0 ? '已逾期 · ' + hm : '已逾期 ' + Math.abs(dd) + ' 天';
  if (dd === 0) return '今天 ' + hm;
  if (dd === 1) return '明天 ' + hm;
  if (dd === 2) return '后天 ' + hm;
  if (dd < 7) return dd + ' 天后 ' + hm;
  return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日 ' + hm;
}
function dueClass(s) {
  const d = parseD(s); if (!d) return 'ok';
  const diff = d - new Date();
  if (diff < 0) return 'over';
  if (diff < 86400000 * 2) return 'soon';
  return 'ok';
}
function relTime(s) {
  const d = parseD(s); if (!d) return '';
  const diff = (Date.now() - d) / 1000;
  if (diff < 0) return '刚刚';
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  const dd = daysBetween(d, new Date());
  if (dd === 0) return '今天';
  if (dd === 1) return '昨天';
  if (dd < 7) return dd + ' 天前';
  return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日';
}
function fmtWhen(s) {
  const d = parseD(s); if (!d) return '';
  const dd = daysBetween(new Date(), d);
  const hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
  if (dd === 0) return '今天 ' + hm;
  if (dd === -1) return '昨天 ' + hm;
  return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + hm;
}

/* 周次解析：支持 "1-18" / "1-8,10-16" / "1-18单" / "1-18双" */
function parseWeeks(spec) {
  if (spec == null || spec === '' || spec === 'all') return null;
  let s = String(spec);
  let parity = 0;
  if (/单/.test(s)) parity = 1;
  if (/双/.test(s)) parity = 2;
  s = s.replace(/[单双周\s]/g, '');
  if (!s) return null;
  const set = new Set();
  s.split(/[,，、;；]/).forEach(part => {
    part = part.trim(); if (!part) return;
    const m = part.match(/^(\d+)\s*[-~至到]\s*(\d+)$/);
    if (m) {
      const a = +m[1], b = +m[2];
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) set.add(i);
    } else if (/^\d+$/.test(part)) set.add(+part);
  });
  if (parity === 1) Array.from(set).forEach(w => { if (w % 2 === 0) set.delete(w); });
  if (parity === 2) Array.from(set).forEach(w => { if (w % 2 === 1) set.delete(w); });
  return set;
}
function inWeek(spec, w) {
  const set = parseWeeks(spec);
  return set === null || set.has(+w);
}
function hexA(hex, a) {
  const h = String(hex || '#8B6F47').replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}
function hashStr(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

/* ==================== 状态 ==================== */
const DEFAULT_SECTIONS = CAMPUS_SECTIONS['校本部 / 珠海'];

function defaultState() {
  return {
    v: 1,
    profile: { name: '', sid: '', college: '' },
    settings: {
      termStart: '2026-09-07',
      totalWeeks: 20,
      campus: '校本部 / 珠海',
      sections: JSON.parse(JSON.stringify(DEFAULT_SECTIONS)),
      showWeekend: false,
      notify: false,
      remindBeforeMin: 30,
      // autoSync / syncTimes 是「每天自动同步」在界面上的**镜像**。
      // 真正执行定时同步的是 Windows 计划任务（sync/register_task.ps1）——
      // 打开工作台时会从 /api/schedule 回读系统里的真实状态覆盖这两个值，
      // 所以别在别处把它们当成真理。
      autoSync: false,
      syncTimes: '08:00,20:00',
      // 手动删过的消息 / 待办 id。同步用的 id 是稳定的，不记这份名单的话，
      // 下次同步会把删掉的东西原样再塞回来。
      dismissed: [],
      demo: false,
      firstRun: true
    },
    courses: [],
    todos: [],
    messages: [],
    cet: {
      type: 'CET-6',
      examDate: '2026-12-19',
      targetScore: 500,
      startedAt: '2026-10-07',
      daily: {},
      tasks: [
        { id: 'vocab', name: '词汇', unit: '个', goal: 50, icon: 'book' },
        { id: 'listen', name: '听力', unit: '篇', goal: 2, icon: 'bell' },
        { id: 'read', name: '阅读', unit: '篇', goal: 2, icon: 'file' },
        { id: 'write', name: '写译', unit: '题', goal: 1, icon: 'pencil' }
      ],
      finalExams: []
    },
    meta: { lastSync: null, syncNote: '', notified: [], connections: [] }
  };
}

let S = defaultState();
let UI = {
  view: 'dash', week: null, todoFilter: 'open',
  msgPlatform: 'all', msgUnreadOnly: false, msgQuery: '',
  courseQuery: '', courseAll: false
};
const API = {
  enabled: location.protocol === 'http:' || location.protocol === 'https:',
  connected: false,
  saving: false,
  lastSaved: null,
  revision: '',
  error: ''
};
let saveTimer = null;
const PLAT = {};
PLATFORMS.forEach(p => { PLAT[p.key] = p; });

function applyState(d) {
  if (!d || typeof d !== 'object') return false;
  S = Object.assign(defaultState(), d);
  S.profile = Object.assign(defaultState().profile, d.profile || {});
  S.settings = Object.assign(defaultState().settings, d.settings || {});
  S.cet = Object.assign(defaultState().cet, d.cet || {});
  S.cet.finalExams = Array.isArray(S.cet.finalExams) ? S.cet.finalExams.filter(e => e && typeof e === 'object').map(e => Object.assign({}, e, { id: String(e.id || uid('final')), title: String(e.title || '期末考试'), date: String(e.date || '') })) : [];
  S.meta = Object.assign(defaultState().meta, d.meta || {});
  S.courses = (d.courses || []).map(normCourse);
  S.todos = (d.todos || []).map(normTodo);
  S.messages = (d.messages || []).map(normMsg);
  return true;
}

function save() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(S)); }
  catch (e) { toast('本地存储写入失败：' + e.message, 'err'); }
  queueServerSave();
}
function load() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      return applyState(JSON.parse(raw));
    }
  } catch (e) { console.warn('读取本地数据失败', e); }
  return false;
}

async function apiRequest(path, options) {
  if (!API.enabled) throw new Error('当前以单文件模式运行');
  const opts = Object.assign({ headers: {} }, options || {});
  if (opts.body && !opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { }
  if (!res.ok) throw new Error((data && data.error) || ('HTTP ' + res.status));
  return data || {};
}

async function loadServerState() {
  if (!API.enabled) return null;
  try {
    const data = await apiRequest('/api/state');
    API.connected = true;
    API.error = '';
    API.revision = data.revision || '';
    return data.state || null;
  } catch (e) {
    API.connected = false;
    API.error = e.message || '连接失败';
    return null;
  }
}

function queueServerSave() {
  if (!API.enabled || !API.connected) return;
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => pushServerState(false), 450);
}

async function pushServerState(showResult) {
  if (!API.enabled || !API.connected || API.saving) return false;
  API.saving = true;
  try {
    const data = await apiRequest('/api/state', { method: 'PUT', body: JSON.stringify({ state: S }) });
    API.revision = data.revision || API.revision;
    API.lastSaved = new Date().toISOString();
    API.error = '';
    if (showResult) toast('已保存到本机数据库', 'ok');
    return true;
  } catch (e) {
    API.connected = false;
    API.error = e.message || '保存失败';
    if (showResult) toast('数据库保存失败，已继续保存在浏览器中', 'warn');
    return false;
  } finally {
    API.saving = false;
  }
}

/* ==================== 数据规范化 ==================== */
function normCourse(c) {
  c.sessions = (c.sessions || []).map(s => ({
    day: +s.day || 1,
    start: +s.start || 1,
    len: +s.len || 1,
    weeks: (s.weeks == null || s.weeks === '') ? ('1-' + (S.settings.totalWeeks - 2)) : String(s.weeks),
    room: s.room || c.room || ''
  })).filter(s => s.day >= 1 && s.day <= 7 && s.start >= 1);
  c.color = c.color || PALETTE[0];
  c.platform = c.platform || '';
  return c;
}
function normMsg(m) {
  return {
    id: m.id || uid('m'),
    platform: m.platform || 'other',
    course: m.course || '',
    courseId: m.courseId || '',
    title: m.title || '(无标题)',
    content: m.content || '',
    url: m.url || '',
    time: m.time || new Date().toISOString(),
    read: !!m.read,
    kind: m.kind || 'notice',
    deadline: m.deadline || ''
  };
}
function normTodo(t) {
  return {
    id: t.id || uid('t'),
    title: t.title || '(未命名)',
    course: t.course || '',
    courseId: t.courseId || '',
    due: t.due || '',
    priority: +t.priority || 2,
    done: !!t.done,
    doneAt: t.doneAt || null,
    note: t.note || '',
    source: t.source || 'manual',
    url: t.url || '',
    createdAt: t.createdAt || new Date().toISOString()
  };
}

/* ==================== 同步数据合并 ==================== */
function mergePayload(payload, silent) {
  const n = { courses: 0, msgs: 0, todos: 0 };
  if (!payload) return n;
  const dismissed = S.settings.dismissed || [];

  (payload.courses || []).forEach(c => {
    const key = c.syncKey || c.id || c.name;
    const ex = S.courses.find(x => (x.syncKey || x.id) === key || x.name === c.name);
    if (ex) {
      ['teacher', 'school', 'url', 'platform', 'sessions', 'room', 'detail'].forEach(k => { if (c[k] != null && c[k] !== '') ex[k] = c[k]; });
      normCourse(ex);
    } else {
      const nc = normCourse(Object.assign({
        id: uid('c'),
        color: PALETTE[S.courses.length % PALETTE.length],
        syncKey: key
      }, c));
      S.courses.push(nc);
      n.courses++;
    }
  });

  (payload.messages || []).forEach(m => {
    const id = m.id || ('s-' + hashStr((m.platform || '') + (m.title || '') + (m.time || '')));
    if (dismissed.indexOf(id) >= 0) return;
    const ex = S.messages.find(x => x.id === id);
    if (ex) {
      Object.assign(ex, {
        title: m.title || ex.title,
        content: m.content || ex.content,
        url: m.url || ex.url,
        time: m.time || ex.time,
        deadline: m.deadline || ex.deadline
      });
    } else {
      // 不强制 read:false —— 同步脚本会把「很旧的历史通知」直接标成已读
      // （翻历史页一次会带回上百条旧通知），这里要尊重它，否则未读角标会被淹没。
      S.messages.push(normMsg(Object.assign({}, m, { id: id })));
      n.msgs++;
    }
  });

  (payload.todos || []).forEach(t => {
    const id = t.id || ('t-' + hashStr((t.title || '') + (t.due || '')));
    if (dismissed.indexOf(id) >= 0) return;
    const ex = S.todos.find(x => x.id === id);
    if (ex) { Object.assign(ex, { due: t.due || ex.due, title: t.title || ex.title }); }
    else { S.todos.push(normTodo(Object.assign({}, t, { id: id }))); n.todos++; }
  });

  S.meta.lastSync = payload.syncedAt || new Date().toISOString();
  S.meta.syncNote = payload.note || '';
  // connections 里带着「登录态还剩几天」，loginHealth 是体检摘要。
  // 这两个只有同步脚本算得出来（要读浏览器的 cookie 到期时间），页面照单全收。
  if (Array.isArray(payload.connections) && payload.connections.length) {
    S.meta.connections = payload.connections;
  }
  if (payload.loginHealth) S.meta.loginHealth = payload.loginHealth;
  if (!silent) save();
  return n;
}

/* 记住「这条我删了」，否则下次同步会把它原样塞回来 */
function dismissId(id) {
  if (!id) return;
  if (!Array.isArray(S.settings.dismissed)) S.settings.dismissed = [];
  if (S.settings.dismissed.indexOf(id) >= 0) return;
  S.settings.dismissed.push(id);
  if (S.settings.dismissed.length > 400) {
    S.settings.dismissed = S.settings.dismissed.slice(-400);
  }
}

function dismissMany(ids) {
  (ids || []).forEach(dismissId);
}

/* ==================== Toast ==================== */
function toast(msg, kind) {
  let wrap = $('#toasts');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'toasts';
    wrap.className = 'toasts';
    document.body.appendChild(wrap);
  }
  const t = document.createElement('div');
  t.className = 'toast ' + (kind || 'ok');
  t.innerHTML = ic(kind === 'ok' ? 'check' : 'warn') + '<span>' + esc(msg) + '</span>';
  wrap.appendChild(t);
  setTimeout(() => {
    t.style.transition = 'opacity .3s,transform .3s';
    t.style.opacity = '0';
    t.style.transform = 'translateY(6px)';
    setTimeout(() => t.remove(), 320);
  }, kind === 'err' ? 5000 : 3200);
}

/* ==================== 弹窗 ==================== */
let modalStack = [];
function openModal(title, bodyHTML, footHTML, opts) {
  opts = opts || {};
  const mask = document.createElement('div');
  mask.className = 'mask';
  mask.innerHTML =
    '<div class="modal' + (opts.wide ? ' wide' : '') + '">' +
      '<div class="modal-h"><h3>' + esc(title) + '</h3>' +
        '<button class="icon-btn" data-close="1" title="关闭">' + ic('x') + '</button></div>' +
      '<div class="modal-b"></div>' +
      (footHTML ? '<div class="modal-f">' + footHTML + '</div>' : '') +
    '</div>';
  $('.modal-b', mask).innerHTML = bodyHTML;
  mask.addEventListener('mousedown', e => { if (e.target === mask) closeModal(); });
  $('[data-close]', mask).addEventListener('click', closeModal);
  document.body.appendChild(mask);
  modalStack.push(mask);
  const first = mask.querySelector('input,select,textarea');
  if (first) setTimeout(() => first.focus(), 70);
  return mask;
}
function closeModal() { const m = modalStack.pop(); if (m) m.remove(); }
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && modalStack.length) closeModal();
});
function confirmBox(title, text, onOk, okLabel) {
  const m = openModal(title,
    '<p style="margin:0;font-size:13.5px;color:var(--text-2);line-height:1.7">' + text + '</p>',
    '<button class="btn" data-no>取消</button><button class="btn btn-danger" data-yes>' + esc(okLabel || '确认') + '</button>');
  $('[data-no]', m).onclick = closeModal;
  $('[data-yes]', m).onclick = () => { closeModal(); onOk(); };
}

/* ==================== 计算 ==================== */
function weekOf(date) {
  const st = parseD(S.settings.termStart + 'T00:00:00');
  if (!st) return 1;
  return Math.floor(daysBetween(st, date) / 7) + 1;
}
function dateOf(week, weekday) {
  const st = parseD(S.settings.termStart + 'T00:00:00');
  if (!st) return null;
  const d = new Date(st);
  d.setDate(d.getDate() + (week - 1) * 7 + (weekday - 1));
  return d;
}
function sessionsOn(week, weekday) {
  const out = [];
  (S.courses || []).forEach(c => (c.sessions || []).forEach(s => {
    if (+s.day === +weekday && inWeek(s.weeks, week)) out.push({ c: c, s: s });
  }));
  return out.sort((a, b) => a.s.start - b.s.start);
}
function sections() { return S.settings.sections || DEFAULT_SECTIONS; }
function secTime(i) {
  const sec = sections()[i - 1];
  return sec ? { start: sec[0], end: sec[1] } : { start: '--:--', end: '--:--' };
}
function openTodos() { return S.todos.filter(t => !t.done); }
function overdueTodos() {
  const now = new Date();
  return openTodos().filter(t => { const d = parseD(t.due); return d && d < now; });
}
function unreadMsgs() { return S.messages.filter(m => !m.read); }
function courseOf(idOrName) { return S.courses.find(x => x.id === idOrName || x.name === idOrName); }

/* 「本学期在上的课」= 自己录进来的课（课表导入 / 手动新增），或至少排了课时段的课。
   平台同步回来的课程（带 syncKey）绝大多数是课程池里的历史课 / 全部学期，
   25 门里可能只有几门是当下要上的 —— 它们默认不进课程管理界面，按需切换到「全部」再看。
   注意：这里的判据必须和 mergePayload() 对齐 —— 课表课只在按名字撞车时被更新字段，
   不会被写入 syncKey，所以「无 syncKey」是稳定可靠的标志。 */
function myCourses() {
  return S.courses.filter(c => !c.syncKey || (c.sessions || []).length);
}
function isMyCourse(c) { return !c.syncKey || (c.sessions || []).length; }
/* 下拉选项用：本学期课程，外加「当前已关联的那一门」——
   避免编辑历史待办时，它关联的课不在列表里，一保存就把关联弄丢了。 */
function courseOptionsFor(cur) {
  const list = myCourses().slice();
  [cur && cur.courseId, cur && cur.course].forEach(k => {
    if (!k) return;
    const c = S.courses.find(x => x.id === k || x.name === k);
    if (c && list.indexOf(c) < 0) list.push(c);
  });
  return list;
}

/* ==================== 侧栏 ==================== */
const NAV = [
  { g: '概览', items: [{ k: 'dash', t: '总览', i: 'home' }] },
  { g: '学习', items: [
    { k: 'tt', t: '我的课表', i: 'cal' },
    { k: 'todo', t: '待办事项', i: 'check', badge: () => overdueTodos().length },
    { k: 'inbox', t: '消息中心', i: 'inbox', badge: () => unreadMsgs().length, soft: true },
    { k: 'courses', t: '课程管理', i: 'book' }
  ] },
  { g: '备考', items: [{ k: 'cet', t: '备考与考试', i: 'target' }] },
  { g: '其他', items: [
    { k: 'plat', t: '平台入口', i: 'link' },
    { k: 'set', t: '设置', i: 'cog' }
  ] }
];

function renderSidebar() {
  const nav = $('#nav');
  if (!nav) return;
  nav.innerHTML = NAV.map(grp =>
    '<div class="nav-group">' + grp.g + '</div>' +
    grp.items.map(it => {
      const b = it.badge ? it.badge() : 0;
      return '<button class="nav-item' + (UI.view === it.k ? ' on' : '') + '" data-view="' + it.k + '">' +
        ic(it.i) + '<span>' + it.t + '</span>' +
        (b > 0 ? '<span class="nav-badge' + (it.soft ? ' soft' : '') + '">' + b + '</span>' : '') +
        '</button>';
    }).join('')
  ).join('');
  $$('.nav-item', nav).forEach(b => b.onclick = () => { UI.view = b.dataset.view; render(); window.scrollTo(0, 0); });

  const foot = $('#navFoot');
  if (foot) {
    const syncText = S.meta.lastSync ? '同步于 ' + relTime(S.meta.lastSync) : '尚未同步';
    foot.innerHTML = '<span class="sidebar-avatar">' + esc((S.profile.name || '我').slice(0, 1)) + '</span>' +
      '<span class="sidebar-user"><b>' + esc(S.profile.name || '我的工作台') + '</b>' +
      '<span><i class="sync-dot ' + (S.meta.lastSync ? 'ok' : 'bad') + '"></i>' + syncText + '</span></span>' +
      '<span class="sidebar-cog">' + ic('cog') + '</span>';
    foot.onclick = () => { UI.view = 'set'; render(); window.scrollTo(0, 0); };
  }
}

const MOBILE_NAV = [
  { k: 'dash', t: '首页', i: 'home' },
  { k: 'tt', t: '课表', i: 'cal' },
  { k: 'todo', t: '待办', i: 'check', badge: () => overdueTodos().length },
  { k: 'inbox', t: '消息', i: 'inbox', badge: () => unreadMsgs().length }
];

function renderMobileNav() {
  const nav = $('#mobileNav');
  if (!nav) return;
  const moreActive = ['courses', 'cet', 'plat', 'set'].indexOf(UI.view) >= 0;
  nav.innerHTML = MOBILE_NAV.map(it => {
    const b = it.badge ? it.badge() : 0;
    return '<button class="mobile-nav-item' + (UI.view === it.k ? ' on' : '') + '" data-mview="' + it.k + '">' +
      '<span class="mobile-nav-icon">' + ic(it.i) + (b ? '<i>' + b + '</i>' : '') + '</span><span>' + it.t + '</span></button>';
  }).join('') +
  '<button class="mobile-nav-item' + (moreActive ? ' on' : '') + '" id="mobileMore">' +
    '<span class="mobile-nav-icon">' + ic('grid') + '</span><span>更多</span></button>';
  $$('[data-mview]', nav).forEach(b => b.onclick = () => {
    UI.view = b.dataset.mview; render(); window.scrollTo(0, 0);
  });
  $('#mobileMore', nav).onclick = openMobileMore;
}

function openMobileMore() {
  const items = [
    { k: 'courses', t: '课程管理', i: 'book' },
    { k: 'cet', t: '备考与考试', i: 'target' },
    { k: 'plat', t: '平台入口', i: 'link' },
    { k: 'set', t: '设置', i: 'cog' }
  ];
  const m = openModal('更多功能', '<div class="mobile-more-grid">' + items.map(it =>
    '<button data-more-view="' + it.k + '">' + ic(it.i) + '<span>' + it.t + '</span></button>').join('') + '</div>');
  $$('[data-more-view]', m).forEach(b => b.onclick = () => {
    UI.view = b.dataset.moreView; closeModal(); render(); window.scrollTo(0, 0);
  });
}

/* ==================== 顶栏 ==================== */
function greeting() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}
function renderTopbar() {
  const now = new Date();
  const w = weekOf(now);
  const wk = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()];
  const exam = parseD(S.cet.examDate + 'T00:00:00');
  const titles = { dash: '', tt: '我的课表', todo: '待办事项', inbox: '消息中心', courses: '课程管理',
    cet: '备考与考试', plat: '平台入口', set: '设置' };
  const left = $('#topL');
  if (left) {
    const title = UI.view === 'dash' ? (greeting() + (S.profile.name ? '，' + esc(S.profile.name) : '')) : titles[UI.view];
    left.innerHTML =
      '<h2>' + title + '</h2>' +
      '<p>' + now.getFullYear() + ' 年 ' + (now.getMonth() + 1) + ' 月 ' + now.getDate() + ' 日 星期' + wk +
      ' · 第 <b style="color:var(--text)">' + w + '</b> / ' + S.settings.totalWeeks + ' 教学周' +
      (exam ? ' · 距 ' + S.cet.type + ' 还有 <b style="color:var(--text)">' + Math.max(0, daysBetween(now, exam)) + '</b> 天' : '') +
      '</p>';
  }
  const right = $('#topR');
  if (right) {
    right.innerHTML =
      (API.enabled ? '<div class="pill db-pill ' + (API.connected ? 'online' : 'offline') + '" title="' +
        esc(API.connected ? '数据正在保存到本机 SQLite 数据库' : '后端未连接，当前使用浏览器缓存') + '">' +
        '<span class="sync-dot ' + (API.connected ? 'ok' : 'bad') + '"></span><span>' +
        (API.connected ? '数据库已连接' : '离线缓存') + '</span></div>' : '') +
      '<button class="icon-btn" id="btnSearch" title="全局搜索（/）">' + ic('search') + '</button>' +
      '<button class="icon-btn" id="btnSync" title="数据同步">' + ic('refresh') + '</button>' +
      '<button class="icon-btn" id="btnBell" title="测试提醒">' + ic('bell') + '</button>' +
      '<button class="btn btn-primary top-add" id="btnNewTodo">' + ic('plus') + '<span>新建待办</span></button>';
    $('#btnSearch').onclick = globalSearch;
    $('#btnSync').onclick = API.connected ? triggerSync : showSyncHelp;
    $('#btnBell').onclick = testNotify;
    $('#btnNewTodo').onclick = () => editTodo(null);
  }
}
