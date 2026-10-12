const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

/**
 * 每天一条速报。
 *
 * 为什么是「速报」而不是「截止前 N 小时提醒」：
 *   实测当前抓到的待办里，绝大多数**根本没有写截止时间** —— 老师发通知常说
 *   「习题1」「第一次作业提交」，就是不写几号交。如果只做到期提醒，
 *   这些待办一辈子都不会提醒你。用户要的原话是「每天都会发消息提醒我
 *   当天新增消息和待办」，所以正确的形态是**每天固定一条汇总**：
 *   今天新增了几条、有什么接下来要到期、还有多少积压。
 *
 * 触发时间在 config.json 里（默认每天 20:30，微信云定时按北京时间）。
 *
 * 关于额度（微信硬规则，不是 bug）：
 *   个人主体只有「一次性订阅」—— 用户点一次「允许」能发一条，发完清零。
 *   所以这里坚持「当天真的有事才发」，没事绝不空耗一条额度。
 */
const TEMPLATE_ID = process.env.TEMPLATE_ID || ''
const MP_STATE = process.env.MP_STATE || 'trial' // trial=体验版, formal=正式版
// 设成 true 就每天必发（哪怕一条待办都没有），默认只在有事时发
const ALWAYS_SEND = String(process.env.ALWAYS_SEND || '').toLowerCase() === 'true'

// 模板字段名由你申请的那张模板决定，默认对应
// 「待办事项 thing / 截止时间 time / 来源 thing」
const F_TITLE = process.env.FIELD_TITLE || 'thing1'
const F_TIME = process.env.FIELD_TIME || 'time2'
const F_SOURCE = process.env.FIELD_SOURCE || 'thing3'

const DAY = 24 * 3600 * 1000
const HOUR8 = 8 * 3600 * 1000

/** 云函数跑在 UTC，但「今天」必须是用户那边的今天，所以手动 +8 */
function bjDayStart(ms) {
  const d = new Date(Number(ms) + HOUR8)
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - HOUR8
}

function fmtWhen(ms) {
  if (!ms) return ''
  const d = new Date(Number(ms) + HOUR8)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}

/** 订阅消息的 thing 字段限 20 字，超了整条会发失败 */
function cut(s, n) {
  const v = String(s == null ? '' : s).replace(/\s+/g, ' ').trim()
  if (!v) return '—'
  return v.length > n ? v.slice(0, n - 1) + '…' : v
}

/** 算出「今天新增 / 接下来到期 / 已逾期 / 总积压」，并挑出一条最该被看见的 */
async function collect(openid, now) {
  const todayStart = bjDayStart(now)
  const horizon = todayStart + 2 * DAY // 覆盖今天剩下 + 整个明天

  const [created, dueSoon, overdue, pending] = await Promise.all([
    db
      .collection('todos')
      .where({ _openid: openid, done: false, createdAt: _.and(_.gte(todayStart), _.lte(now)) })
      .count(),
    db
      .collection('todos')
      .where({ _openid: openid, done: false, dueAt: _.and(_.gt(now), _.lte(horizon)) })
      .orderBy('dueAt', 'asc')
      .limit(10)
      .get(),
    db
      .collection('todos')
      .where({ _openid: openid, done: false, dueAt: _.and(_.gt(0), _.lte(now)) })
      .count(),
    db.collection('todos').where({ _openid: openid, done: false }).count(),
  ])

  let highlight = dueSoon.data[0] || null
  if (!highlight && created.total) {
    // 没有快到期的，就把今天刚进来的那条拿出来 —— 「今天新增了什么」正是用户想知道的
    const latest = await db
      .collection('todos')
      .where({ _openid: openid, done: false })
      .orderBy('createdAt', 'desc')
      .limit(1)
      .get()
    highlight = latest.data[0] || null
  }

  return {
    createdAt: created.total,
    dueSoon: dueSoon.data,
    overdue: overdue.total,
    pending: pending.total,
    highlight,
  }
}

function headlineOf(s) {
  const parts = []
  if (s.createdAt) parts.push(`新增 ${s.createdAt} 条`)
  if (s.dueSoon.length) parts.push(`${s.dueSoon.length} 条将到期`)
  if (parts.length) return parts.join(' · ')
  // 今天没新增也没到期 —— 只在有积压时才发，语气换成「提醒你还有事」
  if (s.overdue) return `${s.overdue} 条已逾期未完成`
  if (s.pending) return `还有 ${s.pending} 条待办未完成`
  return ''
}

async function sendTo(binding, now) {
  const openid = binding._openid
  const s = await collect(openid, now)
  const headline = headlineOf(s)

  if (!headline && !ALWAYS_SEND) {
    return { openid, sent: false, skipped: 'nothing-to-say' }
  }

  const dueAt = (s.dueSoon[0] && s.dueSoon[0].dueAt) || null
  const payload = {}
  payload[F_TITLE] = { value: cut(headline || '今天没有待办', 20) }
  payload[F_TIME] = { value: fmtWhen(dueAt || now) }
  payload[F_SOURCE] = { value: cut(s.highlight ? s.highlight.title : '点开看看', 20) }

  try {
    await cloud.openapi.subscribeMessage.send({
      touser: openid,
      templateId: TEMPLATE_ID,
      page: 'pages/index/index',
      miniprogramState: MP_STATE,
      lang: 'zh_CN',
      data: payload,
    })
  } catch (e) {
    const code = e && (e.errCode || e.code)
    // 43101 = 用户没有订阅额度了。这是常态（一次性订阅的规则），不是故障。
    await db.collection('bindings').doc(binding._id).update({
      data: { lastDigestAt: now, lastDigestNote: code === 43101 ? 'no-quota' : String(code || 'error') },
    })
    return { openid, sent: false, skipped: code === 43101 ? 'no-quota' : 'failed', err: String(code || e) }
  }

  await db.collection('bindings').doc(binding._id).update({
    data: { lastDigestAt: now, lastDigestNote: 'sent', quota: _.inc(-1) },
  })
  // 说明这次提醒是为哪些待办发的，方便在「我的」页面回溯
  for (const t of s.dueSoon) {
    await db.collection('todos').doc(t._id).update({ data: { reminded: true, remindedAt: now } })
  }
  return { openid, sent: true, headline, dueAt, pending: s.pending }
}

exports.main = async () => {
  if (!TEMPLATE_ID) {
    return { ok: false, error: 'NO_TEMPLATE', message: '云函数 remind 还没配 TEMPLATE_ID 环境变量' }
  }

  const now = Date.now()
  const todayStart = bjDayStart(now)

  const binds = await db.collection('bindings').limit(100).get()
  const out = { ok: true, at: new Date(now + HOUR8).toISOString().replace('T', ' ').slice(0, 16), users: 0, sent: 0, skipped: 0, detail: [] }

  for (const b of binds.data) {
    out.users++
    // 同一天只发一次：定时器万一被重放，也不该多耗用户一条额度
    const last = Number(b.lastDigestAt || 0)
    if (last && bjDayStart(last) === todayStart) {
      out.skipped++
      out.detail.push({ openid: b._openid, skipped: 'already-sent-today' })
      continue
    }
    const r = await sendTo(b, now)
    if (r.sent) {
      out.sent++
      out.detail.push({ openid: r.openid, sent: true, headline: r.headline, pending: r.pending })
    } else {
      out.skipped++
      out.detail.push({ openid: r.openid, skipped: r.skipped, err: r.err })
    }
  }

  out.message = `共 ${out.users} 个用户，发出 ${out.sent} 条，跳过 ${out.skipped} 条`
  return out
}
