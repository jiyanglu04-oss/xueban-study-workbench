const config = require('./config.js')

App({
  /**
   * 全局只留「身份」和「订阅额度」两类状态 —— 待办数据一律现取现用，
   * 免得本地缓存和云端各说各话（那正是旧的单文件版踩过的坑）。
   */
  globalData: {
    openid: '',
    bindCode: '',
    quota: 0,
    envReady: false,
  },

  onLaunch() {
    if (!wx.cloud) {
      wx.showModal({
        title: '基础库版本过低',
        content: '请在微信开发者工具里把「调试基础库」调到 2.2.3 以上，否则云开发不可用。',
        showCancel: false,
      })
      return
    }
    if (!config.ENV_ID) {
      // 首次打开时环境往往还没配好，这里不打断，交给页面去提示
      console.warn('[学伴] 还没填云开发环境 ID，见 miniprogram/config.js')
    }
    wx.cloud.init({
      env: config.ENV_ID || undefined,
      traceUser: true,
    })
    this.globalData.envReady = !!config.ENV_ID
  },

  /** 统一的云函数调用：出错时把提示语收敛到一处，页面里就不用到处写 try/catch */
  call(name, data) {
    return wx.cloud
      .callFunction({ name, data: data || {} })
      .then((res) => {
        const r = res && res.result
        if (r && r.ok === false) {
          return Promise.reject(new Error(r.message || r.error || '调用失败'))
        }
        return r
      })
  },
})
