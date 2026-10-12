const app = getApp()
const { fmtDue, relTime } = require('../../utils/format.js')

Page({
  data: {
    ready: false,
    needEnv: false,
    tab: 'open', // open = 未完成，done = 已完成
    list: [],
    openCount: 0,
    doneCount: 0,
    loading: true,
  },

  onLoad() {
    const ready = !!app.globalData.envReady
    this.setData({ ready, needEnv: !ready })
  },

  onShow() {
    if (app.globalData.envReady) this.refresh()
  },

  onPullDownRefresh() {
    this.refresh().then(() => wx.stopPullDownRefresh())
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
    if (tab === this.data.tab) return
    this.setData({ tab }, () => this.refresh())
  },

  refresh() {
    if (!app.globalData.envReady) {
      this.setData({ needEnv: true, ready: false })
      return Promise.resolve()
    }
    const db = wx.cloud.database()
    const now = Date.now()
    const done = this.data.tab === 'done'

    return Promise.all([
      db.collection('todos').where({ done }).orderBy('dueAt', 'asc').limit(200).get(),
      db.collection('todos').where({ done: false }).count(),
      db.collection('todos').where({ done: true }).count(),
    ])
      .then(([res, c1, c2]) => {
        const list = (res.data || []).map((d) => {
          const due = fmtDue(d.dueAt, now)
          return {
            id: d.id || d._id,
            _id: d._id,
            title: d.title || '(无标题)',
            course: d.course || '',
            platform: d.platform || '',
            url: d.url || '',
            done: !!d.done,
            dueText: due.text,
            dueTone: due.tone,
            ingestText: relTime(d.ingestAt, now),
          }
        })
        this.setData({
          ready: true,
          needEnv: false,
          list,
          openCount: c1.total || 0,
          doneCount: c2.total || 0,
          loading: false,
        })
      })
      .catch((e) => {
        this.setData({ loading: false })
        wx.showToast({ title: (e && e.message) || '读取失败', icon: 'none' })
      })
  },

  /** 完成 / 撤销。勾选状态以手机为准，本机同步不会覆盖它 */
  onToggle(e) {
    const { docid } = e.currentTarget.dataset
    const target = !(e.currentTarget.dataset.done === true || e.currentTarget.dataset.done === 'true')
    if (!docid) return
    wx.cloud
      .database()
      .collection('todos')
      .doc(docid)
      .update({ data: { done: target, doneAt: target ? Date.now() : null } })
      .then(() => {
        wx.showToast({ title: target ? '已完成' : '已恢复' })
        this.refresh()
      })
      .catch(() => wx.showToast({ title: '操作失败', icon: 'none' }))
  },

  onOpenUrl(e) {
    const url = e.currentTarget.dataset.url
    if (!url) return
    wx.setClipboardData({ data: url, success: () => wx.showToast({ title: '链接已复制' }) })
  },
})
