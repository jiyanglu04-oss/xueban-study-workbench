/**
 * 时间显示。手机屏幕小，能省的字都省掉 —— 只保留「几点、哪一天」。
 * 云函数跑在 UTC，但这里拿到的是时间戳，一律按北京时间（UTC+8）换算。
 */
const HOUR = 3600 * 1000
const DAY = 24 * HOUR

function bjParts(ms) {
  const d = new Date(Number(ms) + 8 * HOUR)
  const p = (n) => String(n).padStart(2, '0')
  return {
    y: d.getUTCFullYear(),
    m: d.getUTCMonth() + 1,
    d: d.getUTCDate(),
    hh: p(d.getUTCHours()),
    mm: p(d.getUTCMinutes()),
    week: d.getUTCDay(),
  }
}

/** 当天 0 点（北京时间）的时间戳，用来算「差几天」 */
function bjDayStart(ms) {
  const p = bjParts(ms)
  return Date.UTC(p.y, p.m - 1, p.d) - 8 * HOUR
}

const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/**
 * 截止时间的人话版本。
 * 返回 { text, tone } —— tone 给前端决定颜色：red=已过期 orange=今天 yellow=明天 ''=更远
 */
function fmtDue(ms, now) {
  const t = Number(ms)
  if (!t) return { text: '没有截止时间', tone: '' }
  const cur = now || Date.now()
  const p = bjParts(t)
  const diffDays = Math.round((bjDayStart(t) - bjDayStart(cur)) / DAY)
  const clock = p.hh + ':' + p.mm

  if (diffDays < 0) {
    const n = -diffDays
    return { text: (n === 1 ? '昨天' : n + ' 天前') + ' ' + clock, tone: 'red' }
  }
  if (diffDays === 0) {
    if (t < cur) return { text: '今天 ' + clock + '（已过）', tone: 'red' }
    return { text: '今天 ' + clock, tone: 'orange' }
  }
  if (diffDays === 1) return { text: '明天 ' + clock, tone: 'yellow' }
  if (diffDays === 2) return { text: '后天 ' + clock, tone: 'yellow' }
  if (diffDays < 7) return { text: WEEK[p.week] + ' ' + clock, tone: '' }
  return { text: p.m + '月' + p.d + '日 ' + clock, tone: '' }
}

/** 「3 分钟前」「昨天 20:11」这种相对时间，用在「最近同步」上 */
function relTime(ms, now) {
  const t = Number(ms)
  if (!t) return '还没同步过'
  const cur = now || Date.now()
  const diff = cur - t
  if (diff < 0) return '刚刚'
  if (diff < 60 * 1000) return '刚刚'
  if (diff < HOUR) return Math.floor(diff / (60 * 1000)) + ' 分钟前'
  const p = bjParts(t)
  const diffDays = Math.round((bjDayStart(cur) - bjDayStart(t)) / DAY)
  if (diffDays === 0) return p.hh + ':' + p.mm
  if (diffDays === 1) return '昨天 ' + p.hh + ':' + p.mm
  if (diffDays < 7) return diffDays + ' 天前'
  return p.m + '月' + p.d + '日'
}

module.exports = { fmtDue, relTime, bjParts, bjDayStart }
