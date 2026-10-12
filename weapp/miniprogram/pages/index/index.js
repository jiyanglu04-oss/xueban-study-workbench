const app = getApp()
const config = require('../../config.js')
const { fmtDue, relTime } = require('../../utils/format.js')

// 没勾「总是保持以上选择」时，每次冷启动都弹订阅窗会很烦。
// 折中：额度少于这个数、且距上次请求超过 2 小时，才静默补一次。
const MIN_QUOTA = 3
const RESUBSCRIBE_GAP = 2 * 3600 * 1000

Page({
  data: {
    ready: false,
    needEnv: false,
    groups: [],
    total: 0,
    unreadMsgs: 0,
    quota: 0,
    quotaLow: false,
    lastSyncText: '',
    lastSyncStale: false,
    refreshing: false,
    startedAt: Date.now(),
  },

  onLoad() {
    const ready = !!app.globalData.envReady
    this.setData({ ready, needEnv: !ready })
    if (ready) this.refresh()
  },

  onShow() {
    if (app.globalData.envReady) this.refresh()
  },

  onPullDownRefresh() {
    this.refresh().then(() => wx.stopPullDownRefresh())
  },

  /** 拉云端待办 + 身份信息，一次并成两个请求发出去 */
  refresh() {
    if (!app.globalData.envReady) {
      this.setData({ needEnv: true, ready: false })
      return Promise.resolve()
    }
    this.setData({ refreshing: true })
    const db = wx.cloud.database()
    const now = Date.now()

    return Promise.all([
      db.collection('todos').where({ done: false }).orderBy('dueAt', 'asc').limit(200).get(),
      db.collection('messages').where({ read: false }).count(),
      app.call('bind', { action: 'get' }).catch(() => null),
    ])
      .then(([res, unreadMsgs, info]) => {
        const list = (res.data || []).map((d) => {
          const due = fmtDue(d.dueAt, now)
          return {
            id: d.id || d._id,
            _id: d._id,
            title: d.title || '(无标题)',
            course: d.course || '',
            platform: d.platform || '',
            url: d.url || '',
            priority: Number(d.priority) || 2,
            dueText: due.text,
            dueTone: due.tone,
          }
        })
        const groups = []
        const bucket = (label, tone, items) => {
          if (items.length) groups.push({ label, tone, items })
        }
        bucket('已逾期', 'red', list.filter((x) => x.dueTone === 'red'))
        bucket('今天要做', 'orange', list.filter((x) => x.dueTone === 'orange'))
        bucket('接下来', '', list.filter((x) => x.dueTone !== 'red' && x.dueTone !== 'orange'))

        const quota = info ? Number(info.quota) || 0 : this.data.quota
        const stale = info && info.lastIngestAt
          ? now - Number(info.lastIngestAt) > 36 * 3600 * 1000
          : true

        this.setData({
          ready: true,
          needEnv: false,
          groups,
          total: list.length,
          unreadMsgs: unreadMsgs.total || 0,
          quota,
          quotaLow: quota < MIN_QUOTA,
          lastSyncText: info ? relTime(info.lastIngestAt, now) : '未知',
          lastSyncStale: !!stale,
          refreshing: false,
        })

        // 待办为空或额度够用就不打扰；否则顺手补一次订阅额度
        if (this.data.quotaLow) this.autoSubscribe()
      })
      .catch((e) => {
        this.setData({ refreshing: false })
        wx.showToast({ title: (e && e.message) || '读取失败', icon: 'none' })
      })
  },

  /**
   * 订阅额度。微信规则下个人主体只能一次性订阅，所以「攒额度」是这里的核心动作。
   * 调多一点没坏处：已经勾了「总是保持以上选择」的用户不会再看到弹窗。
   */
  requestSubscribe() {
    const ids = (config.TEMPLATE_IDS || []).slice(0, 3)
    if (!ids.length) {
      wx.showModal({
        title: '还没配订阅模板',
        content: '先在 mp.weixin.qq.com 申请一个订阅消息模板，把模板 ID 填进 config.js 的 TEMPLATE_IDS。',
        showCancel: false,
      })
      return Promise.resolve(false)
    }
    return new Promise((resolve) => {
      wx.requestSubscribeMessage({
        tmplIds: ids,
        success: (res) => {
          const accepted = ids.filter((id) => res[id] === 'accept').length
          if (!accepted) {
            wx.showToast({ title: '没有授权，就收不到提醒', icon: 'none' })
            resolve(false)
            return
          }
          app
            .call('bind', { action: 'grant', count: accepted })
            .then((info) => {
              this.setData({ quota: Number(info.quota) || 0, quotaLow: (Number(info.quota) || 0) < MIN_QUOTA })
              wx.showToast({ title: '已增加 ' + accepted + ' 条提醒额度' })
              resolve(true)
            })
            .catch(() => resolve(false))
        },
        fail: () => resolve(false),
      })
    })
  },

  /** 后台静默补额度：只在很久没请求过的时候做，避免每次打开都弹窗 */
  autoSubscribe() {
    const last = Number(wx.getStorageSync('lastSubscribeAt') || 0)
    if (Date.now() - last < RESUBSCRIBE_GAP) return
    wx.setStorageSync('lastSubscribeAt', Date.now())
    this.requestSubscribe()
  },

  onTapSubscribe() {
    this.requestSubscribe()
  },

  /** 勾掉一条待办。这里只把「已完成」推给云端，本机的下一次同步不会把它翻回来 */
  onToggleDone(e) {
    const { id, docid } = e.currentTarget.dataset
    if (!docid) return
    wx.cloud
      .database()
      .collection('todos')
      .doc(docid)
      .update({ data: { done: true, doneAt: Date.now() } })
      .then(() => {
        wx.showToast({ title: '已完成' })
        this.refresh()
      })
      .catch(() => wx.showToast({ title: '操作失败', icon: 'none' }))
  },

  onOpenUrl(e) {
    const url = e.currentTarget.dataset.url
    if (!url) return
    // 小程序不能直接开外部网页，复制链接让用户在浏览器里打开是唯一稳定的做法
    wx.setClipboardData({ data: url, success: () => wx.showToast({ title: '链接已复制' }) })
  },

  onGoMe() {
    wx.switchTab({ url: '/pages/me/me' })
  },

  onGoNotice() {
    wx.navigateTo({ url: '/pages/notice/notice' })
  },
})
