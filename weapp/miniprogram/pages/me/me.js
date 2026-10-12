const app = getApp()
const config = require('../../config.js')
const { relTime } = require('../../utils/format.js')

Page({
  data: {
    ready: false,
    needEnv: false,
    bindCode: '',
    codeGroups: [],
    quota: 0,
    pending: 0,
    lastSyncText: '未知',
    lastSyncStale: false,
    lastRemindText: '还没提醒过',
    templateCount: 0,
    showGuide: false,
    loading: true,
  },

  onLoad() {
    const ready = !!app.globalData.envReady
    this.setData({ ready, needEnv: !ready, templateCount: (config.TEMPLATE_IDS || []).length })
  },

  onShow() {
    if (app.globalData.envReady) this.refresh()
  },

  onPullDownRefresh() {
    this.refresh().then(() => wx.stopPullDownRefresh())
  },

  refresh() {
    if (!app.globalData.envReady) {
      this.setData({ needEnv: true, ready: false })
      return Promise.resolve()
    }
    const now = Date.now()
    return app
      .call('bind', { action: 'get' })
      .then((info) => {
        const code = String(info.bindCode || '')
        this.setData({
          ready: true,
          needEnv: false,
          bindCode: code,
          // 8 位码拆成 4+4，手机上看、手抄都不容易串行
          codeGroups: [code.slice(0, 4), code.slice(4, 8)],
          quota: Number(info.quota) || 0,
          pending: Number(info.pending) || 0,
          lastSyncText: relTime(info.lastIngestAt, now),
          lastSyncStale: info.lastIngestAt ? now - Number(info.lastIngestAt) > 36 * 3600 * 1000 : true,
          lastRemindText: info.lastRemindAt ? relTime(info.lastRemindAt, now) : '还没提醒过',
          loading: false,
        })
      })
      .catch((e) => {
        this.setData({ loading: false })
        wx.showToast({ title: (e && e.message) || '读取失败', icon: 'none' })
      })
  },

  onCopyCode() {
    if (!this.data.bindCode) return
    wx.setClipboardData({
      data: this.data.bindCode,
      success: () => wx.showToast({ title: '绑定码已复制' }),
    })
  },

  /** 换码：旧的立刻失效，用来在处理掉「码被别人看到」的情况 */
  onRenewCode() {
    wx.showModal({
      title: '重新生成绑定码？',
      content: '生成后旧码立刻失效，你需要把新码重新填进电脑上的 sync/push_config.json，否则同步会中断。',
      success: (r) => {
        if (!r.confirm) return
        app
          .call('bind', { action: 'renew' })
          .then(() => {
            wx.showToast({ title: '已生成新码' })
            this.refresh()
          })
          .catch(() => wx.showToast({ title: '生成失败', icon: 'none' }))
      },
    })
  },

  onSubscribe() {
    const ids = (config.TEMPLATE_IDS || []).slice(0, 3)
    if (!ids.length) {
      wx.showModal({
        title: '还没配订阅模板',
        content: '先在 mp.weixin.qq.com 申请一个订阅消息模板，把模板 ID 填进 config.js 的 TEMPLATE_IDS。',
        showCancel: false,
      })
      return
    }
    wx.requestSubscribeMessage({
      tmplIds: ids,
      success: (res) => {
        const accepted = ids.filter((id) => res[id] === 'accept').length
        if (!accepted) {
          wx.showToast({ title: '没有授权', icon: 'none' })
          return
        }
        app
          .call('bind', { action: 'grant', count: accepted })
          .then((info) => {
            this.setData({ quota: Number(info.quota) || 0 })
            wx.showToast({ title: '已增加 ' + accepted + ' 条额度' })
          })
          .catch(() => wx.showToast({ title: '记录失败', icon: 'none' }))
      },
      fail: () => wx.showToast({ title: '订阅窗口打不开', icon: 'none' }),
    })
  },

  toggleGuide() {
    this.setData({ showGuide: !this.data.showGuide })
  },
})
