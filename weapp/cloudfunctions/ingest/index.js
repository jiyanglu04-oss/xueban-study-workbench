const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

/**
 * 接收本机（电脑上的 sync.py）推上来的待办快照。
 *
 * 为什么不让本机直连云数据库：
 *   那条路要从小程序后台取 AppSecret 存在电脑上。AppSecret 是全权限凭证，
 *   一旦泄露，别人可以冒充你的小程序调用任何开放接口。这里改成
 *   「云函数 HTTP 触发 + 共享密钥」，本机侧不持有任何高权限凭证，
 *   密钥泄露最多就是别人能往你的待办里写几条数据，风险小得多。
 */
const MAX_ITEMS = 200

function parseEvent(event) {
  // 两种调用方式都要兼容：
  //   1. 云开发的「HTTP 访问服务」→ 参数在 event.body（字符串）
  //   2. 开发者工具里手动测试   → 参数直接摊在 event 上
  let data = event || {}
  let headers = {}
  if (event && typeof event.body === 'string') {
    try {
      data = JSON.parse(event.body || '{}')
    } catch (e) {
      data = {}
    }
    Object.keys(event.headers || {}).forEach((k) => {
      headers[k.toLowerCase()] = event.headers[k]
    })
  }
  return { data, headers }
}

function cut(s, n) {
  const v = String(s == null ? '' : s).replace(/\s+/g, ' ').trim()
  return v.length > n ? v.slice(0, n - 1) + '…' : v
}

function normalizeDue(v) {
  // 兼容 时间戳 / ISO 字符串 / 空
  if (v == null || v === '') return null
  if (typeof v === 'number') return v
  const t = Date.parse(v)
  return isNaN(t) ? null : t
}

exports.main = async (event) => {
  const { data, headers } = parseEvent(event)

  const key = data.key || headers['x-ingest-key'] || ''
  if (!process.env.INGEST_KEY || key !== process.env.INGEST_KEY) {
    return { ok: false, error: 'BAD_KEY', message: '密钥不对，检查云函数环境变量 INGEST_KEY' }
  }

  const bindCode = String(data.bindCode || '').trim().toUpperCase()
  if (!bindCode) {
    return { ok: false, error: 'NO_BIND_CODE', message: '没带绑定码' }
  }

  const bindRes = await db.collection('bindings').where({ bindCode }).limit(1).get()
  if (!bindRes.data.length) {
    return { ok: false, error: 'NO_BINDING', message: '绑定码无效，请在小程序「我的」页面重新生成' }
  }
  const binding = bindRes.data[0]
  const openid = binding._openid

  const incoming = (Array.isArray(data.todos) ? data.todos : []).slice(0, MAX_ITEMS)
  const existing = await db.collection('todos').where({ _openid: openid }).limit(MAX_ITEMS).get()
  const byId = {}
  existing.data.forEach((d) => {
    byId[d.id] = d
  })

  const now = Date.now()
  let added = 0
  let updated = 0

  for (const raw of incoming) {
    const id = String(raw.id || '').trim()
    if (!id) continue

    const dueAt = normalizeDue(raw.dueAt != null ? raw.dueAt : raw.due)
    const prev = byId[id]
    const doc = {
      id,
      title: cut(raw.title || '(无标题)', 60),
      course: cut(raw.course || '', 40),
      platform: cut(raw.platform || '', 20),
      priority: Number(raw.priority) || 2,
      url: String(raw.url || ''),
      dueAt,
      ingestAt: now,
    }

    if (prev) {
      // 「完成」是用户在手机上的动作，同步不能用本机的旧状态把它盖回去
      await db.collection('todos').doc(prev._id).update({ data: doc })
      updated++
    } else {
      await db.collection('todos').add({
        data: Object.assign({ _openid: openid, done: false, reminded: false, createdAt: now }, doc),
      })
      added++
    }
  }

  // ---- 通知也存一份 ----
  // 用户的原话是「看看有没有新的通知和待办」。只推待办的话，那些被判定成
  // 「纯信息」的通知（课件已上传、课堂互动、教材已发）在小程序里就完全看不到，
  // 而它们恰恰是「有没有新消息」的答案。所以这里额外维护一个 messages 集合。
  const incomingMsgs = (Array.isArray(data.messages) ? data.messages : []).slice(0, MAX_ITEMS)
  let msgAdded = 0
  let msgUpdated = 0
  if (incomingMsgs.length) {
    const existingMsgs = await db.collection('messages').where({ _openid: openid }).limit(MAX_ITEMS).get()
    const msgById = {}
    existingMsgs.data.forEach((d) => {
      msgById[d.id] = d
    })

    for (const raw of incomingMsgs) {
      const id = String(raw.id || '').trim()
      if (!id) continue
      const doc = {
        id,
        title: cut(raw.title || '(无标题)', 60),
        course: cut(raw.course || '', 40),
        platform: cut(raw.platform || '', 20),
        kind: String(raw.kind || 'notice'),
        summary: cut(raw.content || raw.summary || '', 120),
        url: String(raw.url || ''),
        pubAt: normalizeDue(raw.time),
        ingestAt: now,
      }
      const prev = msgById[id]
      if (prev) {
        // 「已读」是用户在手机上的动作，同样不能用本机的状态盖回去
        await db.collection('messages').doc(prev._id).update({ data: doc })
        msgUpdated++
      } else {
        await db.collection('messages').add({
          data: Object.assign({ _openid: openid, read: false, createdAt: now }, doc),
        })
        msgAdded++
      }
    }
  }

  await db.collection('bindings').doc(binding._id).update({
    data: { lastIngestAt: now },
  })

  return {
    ok: true,
    added,
    updated,
    total: incoming.length,
    msgAdded,
    msgUpdated,
    message: `待办新增 ${added} 条、更新 ${updated} 条；通知新增 ${msgAdded} 条、更新 ${msgUpdated} 条`,
  }
}
