const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

// 去掉了 I / O / 0 / 1 —— 这串码要手抄到电脑上，长得像的字符最容易出事
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

function makeCode(len = 8) {
  let s = ''
  for (let i = 0; i < len; i++) {
    s += ALPHABET[Math.floor(Math.random() * ALPHABET.length)]
  }
  return s
}

/**
 * 身份与绑定码。
 *
 * 「登录」这件事在这里是零成本的：小程序天然带微信身份（OPENID），
 * 用户不需要注册、不需要填密码、不需要授权头像昵称。
 * 绑定码只解决一个问题 —— 让电脑知道该把数据推给哪个微信。
 */
exports.main = async (event) => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { ok: false, error: 'NO_OPENID', message: '拿不到微信身份，请把调试基础库调到 2.2.3 以上' }
  }

  const action = String(event.action || 'get')
  const col = db.collection('bindings')

  const found = await col.where({ _openid: openid }).limit(1).get()
  let binding = found.data[0]

  if (!binding) {
    const code = makeCode()
    const added = await col.add({
      data: { _openid: openid, bindCode: code, quota: 0, createdAt: Date.now() },
    })
    binding = { _id: added._id, _openid: openid, bindCode: code, quota: 0 }
  }

  if (action === 'renew') {
    const code = makeCode()
    await col.doc(binding._id).update({ data: { bindCode: code } })
    binding.bindCode = code
  }

  if (action === 'grant') {
    // 用户点了订阅弹窗里的「允许」之后，把这次拿到的额度记上。
    // 一次性订阅是「授权一次 = 能发一条」，所以这个数字要攒着用。
    const n = Math.max(1, Math.min(10, Number(event.count) || 1))
    await col.doc(binding._id).update({ data: { quota: _.inc(n) } })
  }

  const [fresh, pending] = await Promise.all([
    col.doc(binding._id).get(),
    db.collection('todos').where({ _openid: openid, done: false }).count(),
  ])
  const doc = fresh.data || {}

  return {
    ok: true,
    openid,
    bindCode: doc.bindCode || binding.bindCode,
    quota: doc.quota || 0,
    pending: pending.total,
    lastIngestAt: doc.lastIngestAt || 0,
    lastRemindAt: doc.lastRemindAt || 0,
  }
}
