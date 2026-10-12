const app = getApp()
const { relTime } = require('../../utils/format.js')

const KIND_LABEL = {
  homework: '作业',
  exam: '考试',
  signup: '报名',
  social: '加群',
  notice: '公告',
}

Page({
  data: {
    ready: false,
    needEnv: false,
    list: [],
    unread: 0,
    loading: true,
    onlyUnread: false,
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

  toggleFilter() {
    this.setData({ onlyUnread: !this.data.onlyUnread }, () => this.refresh())
  },

  refresh() {
    if (!app.globalData.envReady) {
      this.setData({ needEnv: true, ready: false })
      return Promise.resolve()
    }
    const db = wx.cloud.database()
    const now = Date.now()
    const where = this.data.onlyUnread ? { read: false } : {}

    return Promise.all([
      db.collection('messages').where(where).orderBy('pubAt', 'desc').limit(100).get(),
      db.collection('messages').where({ read: false }).count(),
    ])
      .then(([res, cnt]) => {
        const list = (res.data || []).map((d) => ({
          _id: d._id,
          title: d.title || '(无标题)',
          course: d.course || '',
          platform: d.platform || '',
          summary: d.summary || '',
          url: d.url || '',
          kind: d.kind || 'notice',
          kindLabel: KIND_LABEL[d.kind] || '公告',
          timeText: relTime(d.pubAt, now),
          read: !!d.read,
        }))
        this.setData({
          ready: true,
          needEnv: false,
          list,
          unread: cnt.total || 0,
          loading: false,
        })
      })
      .catch((e) => {
        this.setData({ loading: false })
        wx.showToast({ title: (e && e.message) || '读取失败', icon: 'none' })
      })
  },

  /** 点一条就当读过了。不强制、不打卡，看过自然会点开。 */
  onTapItem(e) {
    const { id, url, read } = e.currentTarget.dataset
    if (url) wx.setClipboardData({ data: url, success: () => wx.showToast({ title: '链接已复制' }) })
    if (read || !id) return
    wx.cloud
      .database()
      .collection('messages')
      .doc(id)
      .update({ data: { read: true, readAt: Date.now() } })
      .then(() => {
        const list = this.data.list.map((x) => (x._id === id ? Object.assign({}, x, { read: true }) : x))
        this.setData({ list, unread: Math.max(0, this.data.unread - 1) })
      })
      .catch(() => {})
  },

  onMarkAllRead() {
    if (!this.data.unread) return
    wx.showModal({
      title: '全部标为已读？',
      content: '只影响手机上这个小程序，电脑上的工作台不受影响。',
      success: (r) => {
        if (!r.confirm) return
        const db = wx.cloud.database()
        db.collection('messages')
          .where({ read: false })
          .update({ data: { read: true, readAt: Date.now() } })
          .then(() => {
            wx.showToast({ title: '已全部标记' })
            this.refresh()
          })
          .catch(() => wx.showToast({ title: '操作失败', icon: 'none' }))
      },
    })
  },
})
