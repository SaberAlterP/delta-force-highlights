import { defineStore } from 'pinia'
import { api } from './api'

const LS_PLAYER = 'df.playerId'
const LS_REGIONS = 'df.regions'
const LS_REGIONS_VERSION = 'df.regionsVersion'
const REGIONS_VERSION = '4'
const LS_LIBRARY = 'df.library'      // 视频库 [VideoMeta]
const LS_CURRENT = 'df.current'      // 当前选中的 upload_id
const LS_BASKET = 'df.basket'        // 剪辑列表（跨视频精选片段）
const LS_STRETCH_169 = 'df.stretch169'
const killsKey = (uploadId) => `df.kills.${uploadId}`
const projectSaveTimers = new Map()

function uid() {
  return Math.random().toString(36).slice(2, 10)
}

export const useStore = defineStore('main', {
  state: () => ({
    playerId: localStorage.getItem(LS_PLAYER) || '',

    config: {
      id_region: [0.79, 0.03, 0.995, 0.14],
      prompt_region: [0.43, 0.72, 0.58, 0.84],
      knockdown_keywords: ['击败', '击中头部击败', '灭队', '击倒', '击中头部击倒', '淘汰'],
      sample_fps: 3.0,
      debounce_seconds: 4.0,
      id_match_ratio: 0.7,
      clip_pre_seconds: 20,
      clip_post_seconds: 5,
    },

    regions: null,

    library: [],          // 所有上传的视频 [VideoMeta]
    video: null,          // 当前选中的视频 VideoMeta

    upload: { busy: false, progress: 0, error: '' },
    analyze: { jobId: null, state: 'idle', progress: 0, message: '', error: '' },

    kills: [],            // 当前视频的击杀
    projectSaveStatus: '',
    projectSaveError: '',

    basket: [],           // 剪辑列表（跨视频）[{bid, upload_id, filename, duration, kill_id, time, pre, post, label}]

    stretch169: localStorage.getItem(LS_STRETCH_169) !== 'false',

    export: { jobId: null, state: 'idle', progress: 0, message: '', error: '', files: [], hasMerged: false },

    seekTo: null,
    currentTime: 0,
    showRegions: false,

    // -------- 自动工作流（全页共享一份状态，App 定时刷新）--------
    workflow: null,
    workflowError: '',
    selectedRecordId: null,
    panel: '',            // '' | 'settings' | 'guide' | 'manual'
  }),

  getters: {
    selectedKills: (s) => s.kills.filter(k => k.selected),
    sortedKills: (s) => [...s.kills].sort((a, b) => a.time - b.time),
    basketByVideo: (s) => {
      const groups = {}
      for (const b of s.basket) {
        (groups[b.upload_id] ||= { filename: b.filename, items: [] }).items.push(b)
      }
      return groups
    },
  },

  actions: {
    async loadConfig() {
      try {
        const cfg = await api.getConfig()
        this.config = { ...this.config, ...cfg }
      } catch (e) { /* 后端未启动用默认值 */ }

      const saved = localStorage.getItem(LS_REGIONS)
      const savedVersion = localStorage.getItem(LS_REGIONS_VERSION)
      if (saved && savedVersion === REGIONS_VERSION) {
        this.regions = JSON.parse(saved)
      } else {
        // v4 恢复到最后一个稳定识别基线的区域配置。
        this.regions = {
          id_region: [...this.config.id_region],
          prompt_region: [...this.config.prompt_region],
        }
        this.saveRegions()
      }

      // 恢复视频库 / 剪辑列表 / 当前视频
      // 归档素材不进上传视频库（旧版本会混进来，这里顺手清掉）
      this.library = JSON.parse(localStorage.getItem(LS_LIBRARY) || '[]').filter(v => !String(v.upload_id).startsWith('bundle_'))
      this._persistLibrary()
      if (this.library.length === 0) {
        // 兼容旧版单视频存储：把上一个当前视频迁移进视频库
        const oldV = localStorage.getItem('df.video')
        if (oldV) {
          try { this.library = [JSON.parse(oldV)]; this._persistLibrary() } catch (e) { /* ignore */ }
        }
      }
      this.basket = JSON.parse(localStorage.getItem(LS_BASKET) || '[]')
      // 打开页面默认看对局列表，不自动载入上次上传的录像
    },

    async refreshWorkflow() {
      try { this.workflow = await api.workflowStatus(); this.workflowError = '' }
      catch { this.workflowError = '暂时连不上本地后台，稍后自动重试' }
    },

    async saveWorkflowSettings(values) {
      await api.workflowSettings(values)
      await this.refreshWorkflow()
    },

    setPlayerId(v) {
      this.playerId = v
      localStorage.setItem(LS_PLAYER, v)
    },

    setStretch169(value) {
      this.stretch169 = !!value
      localStorage.setItem(LS_STRETCH_169, String(this.stretch169))
    },

    saveRegions() {
      localStorage.setItem(LS_REGIONS, JSON.stringify(this.regions))
      localStorage.setItem(LS_REGIONS_VERSION, REGIONS_VERSION)
    },

    // -------- 视频库 --------
    _persistLibrary() { localStorage.setItem(LS_LIBRARY, JSON.stringify(this.library)) },

    addToLibrary(meta) {
      if (!this.library.find(v => v.upload_id === meta.upload_id)) {
        this.library.push(meta)
        this._persistLibrary()
      }
    },

    setVideoMeta(meta) {        // 上传完成后调用
      this.addToLibrary(meta)
      this.selectVideo(meta.upload_id)
    },

    async openArchiveVideo(recordId, clipIndex = null) {
      const data = await api.workflowEdit(recordId, clipIndex)
      this.video = data.video
      this.currentTime = 0
      this.analyze = { jobId: null, state: 'idle', progress: 0, message: '', error: '' }
      if (!this.playerId) this.setPlayerId(data.player_id)
      if (data.project_saved) {
        this.kills = data.kills
        localStorage.setItem(killsKey(data.video.upload_id), JSON.stringify(this.kills))
      } else this.ingestKills(data.kills || [])
      this.selectedRecordId = recordId
      this.projectSaveStatus = '已载入归档工程，原片未复制'
      this.projectSaveError = ''
    },

    // 剪辑列表里的片段可能来自归档素材，也可能来自手动上传
    async openSource(uploadId) {
      const m = /^bundle_([0-9a-f]{32})(?:_clip_([0-9a-f]{12}))?$/.exec(uploadId)
      if (!m) { this.selectedRecordId = null; this.selectVideo(uploadId); return }
      if (this.video?.upload_id === uploadId) return
      const record = this.workflow?.records.find(r => r.id === m[1])
      const index = m[2] ? (record?.result?.files || []).findIndex(f => f.sha256?.startsWith(m[2])) : null
      if (index === -1) throw new Error('这段高光已不存在')
      await this.openArchiveVideo(m[1], index)
    },

    selectVideo(upload_id) {
      const v = this.library.find(x => x.upload_id === upload_id)
      if (!v) return
      this.video = v
      this.selectedRecordId = null
      localStorage.setItem(LS_CURRENT, upload_id)
      const sk = localStorage.getItem(killsKey(upload_id))
      this.kills = sk ? JSON.parse(sk) : []
      this.analyze = { jobId: null, state: 'idle', progress: 0, message: '', error: '' }
      this.currentTime = 0
    },

    removeFromLibrary(upload_id) {
      this.library = this.library.filter(v => v.upload_id !== upload_id)
      this._persistLibrary()
      localStorage.removeItem(killsKey(upload_id))
      if (this.video?.upload_id === upload_id) {
        if (this.library.length) this.selectVideo(this.library[0].upload_id)
        else { this.video = null; this.kills = []; localStorage.removeItem(LS_CURRENT) }
      }
    },

    // 删除归档原片或整个集锦包后，移除网页里对应的素材与剪辑列表条目
    forgetArchive(recordId, originalOnly = false) {
      const prefix = `bundle_${recordId}`
      const gone = (id) => originalOnly ? id === prefix : (id === prefix || id.startsWith(prefix + '_'))
      if (this.video && gone(this.video.upload_id)) { this.video = null; this.kills = [] }
      localStorage.removeItem(killsKey(prefix))
      this.basket = this.basket.filter(b => !gone(b.upload_id))
      localStorage.setItem(LS_BASKET, JSON.stringify(this.basket))
    },

    clearVideo() {
      this.library.forEach(v => localStorage.removeItem(killsKey(v.upload_id)))
      this.library = []
      this.video = null
      this.kills = []
      this.basket = []
      this._persistLibrary()
      this._persistBasket()
      localStorage.removeItem(LS_CURRENT)
      this.analyze = { jobId: null, state: 'idle', progress: 0, message: '', error: '' }
      this.export = { jobId: null, state: 'idle', progress: 0, message: '', error: '', files: [], hasMerged: false }
    },

    persistKills() {
      if (this.video) {
        localStorage.setItem(killsKey(this.video.upload_id), JSON.stringify(this.kills))
        if (this.video.workflow_id) {
          const meta = { ...this.video }
          const marks = JSON.parse(JSON.stringify(this.kills))
          clearTimeout(projectSaveTimers.get(meta.upload_id))
          this.projectSaveStatus = '正在保存到归档文件夹…'
          projectSaveTimers.set(meta.upload_id, setTimeout(async () => {
            try {
              await api.workflowSaveProject(meta.workflow_id, meta.upload_id, marks)
              this.projectSaveStatus = '已保存到归档文件夹'
              this.projectSaveError = ''
            } catch (e) {
              this.projectSaveError = e?.response?.data?.detail || '工程保存失败，本页修改仍在本机浏览器中'
            }
          }, 450))
        }
      }
    },

    _clamp(t) {
      const dur = this.video?.duration || 0
      return Math.max(0, Math.min(dur, t))
    },

    ingestKills(rawKills) {
      this.kills = rawKills.map(k => ({
        id: k.id || uid(),
        time: k.time,
        confidence: k.confidence ?? 0,
        id_text: k.id_text || '',
        prompt_text: k.prompt_text || '',
        victim_id: k.victim_id || '',
        confirmed: k.confirmed === true,
        review_required: k.review_required !== false,
        event_type: k.event_type || 'unknown',
        source: k.source || '',
        label: k.label || k.event_name || '',
        pre: this.config.clip_pre_seconds,
        post: this.config.clip_post_seconds,
        selected: k.confirmed === true && k.review_required === false,
      }))
      this.persistKills()
    },

    addManualKill(time) {
      this.kills.push({
        id: uid(),
        time: this._clamp(time),
        confidence: 1,
        id_text: '(手动添加)',
        prompt_text: '',
        label: '',
        pre: this.config.clip_pre_seconds,
        post: this.config.clip_post_seconds,
        selected: true,
      })
      this.persistKills()
    },

    removeKill(id) {
      this.kills = this.kills.filter(k => k.id !== id)
      this.persistKills()
    },

    updateKill(id, patch) {
      const k = this.kills.find(k => k.id === id)
      if (k) {
        Object.assign(k, patch)
        this.persistKills()
        const basketItem = this.basket.find(b => b.upload_id === this.video?.upload_id && b.kill_id === id)
        if (basketItem) {
          Object.assign(basketItem, {
            time: k.time,
            pre: k.pre,
            post: k.post,
            label: k.label || basketItem.label,
          })
          this._persistBasket()
        }
      }
    },

    setSelectedAll(v) {
      this.kills.forEach(k => { k.selected = v })
      this.persistKills()
    },

    clipRange(kill) {
      return { start: this._clamp(kill.time - kill.pre), end: this._clamp(kill.time + kill.post) }
    },

    requestSeek(t) { this.seekTo = { t, ts: Date.now() } },

    // -------- 剪辑列表（精选篮）--------
    _persistBasket() { localStorage.setItem(LS_BASKET, JSON.stringify(this.basket)) },

    addToBasket(kill) {
      if (!this.video) return false
      if (this.basket.find(b => b.upload_id === this.video.upload_id && b.kill_id === kill.id)) {
        return false // 已在列表里
      }
      this.basket.push({
        bid: uid(),
        upload_id: this.video.upload_id,
        filename: this.video.filename,
        duration: this.video.duration,
        kill_id: kill.id,
        time: kill.time,
        pre: kill.pre,
        post: kill.post,
        label: kill.label || '',
      })
      this._persistBasket()
      return true
    },

    addSelectedToBasket() {
      let n = 0
      this.selectedKills.forEach(k => { if (this.addToBasket(k)) n++ })
      return n
    },

    removeFromBasket(bid) {
      this.basket = this.basket.filter(b => b.bid !== bid)
      this._persistBasket()
    },

    clearBasket() { this.basket = []; this._persistBasket() },

    updateBasketItem(bid, patch) {
      const b = this.basket.find(x => x.bid === bid)
      if (b) { Object.assign(b, patch); this._persistBasket() }
    },

    basketRange(b) {
      return { start: Math.max(0, b.time - b.pre), end: Math.min(b.duration || 1e9, b.time + b.post) }
    },

    inBasket(killId) {
      return !!(this.video && this.basket.find(b => b.upload_id === this.video.upload_id && b.kill_id === killId))
    },

    // -------- 上传 --------
    async uploadFile(file) {
      this.upload = { busy: true, progress: 0, error: '' }
      try {
        const meta = await api.uploadVideo(file, (p) => { this.upload.progress = p })
        this.setVideoMeta(meta)
      } catch (e) {
        this.upload.error = e?.response?.data?.detail || e.message || '上传失败'
        throw e
      } finally {
        this.upload.busy = false
      }
    },

    // -------- 识别 --------
    async runAnalyze() {
      if (!this.video) return
      this.analyze = { jobId: null, state: 'running', progress: 0, message: '正在启动…', error: '' }
      try {
        const payload = {
          upload_id: this.video.upload_id,
          player_id: this.playerId,
          sample_fps: this.config.sample_fps,
          debounce_seconds: this.config.debounce_seconds,
          id_match_ratio: this.config.id_match_ratio,
          id_region: this._regionObj(this.regions.id_region),
          prompt_region: this._regionObj(this.regions.prompt_region),
          knockdown_keywords: this.config.knockdown_keywords,
        }
        const { job_id } = await api.startAnalyze(payload)
        this.analyze.jobId = job_id
        await this._pollAnalyze(job_id)
      } catch (e) {
        this.analyze.state = 'error'
        this.analyze.error = e?.response?.data?.detail || e.message || '识别失败'
      }
    },

    _regionObj(arr) { return { x1: arr[0], y1: arr[1], x2: arr[2], y2: arr[3] } },

    async _pollAnalyze(jobId) {
      return new Promise((resolve) => {
        const timer = setInterval(async () => {
          try {
            const s = await api.analyzeStatus(jobId)
            this.analyze.progress = s.progress
            this.analyze.message = s.message
            this.analyze.state = s.state
            if (s.state === 'done') {
              clearInterval(timer); this.ingestKills(s.kills || []); resolve()
            } else if (s.state === 'error') {
              clearInterval(timer); this.analyze.error = s.error || '识别失败'; resolve()
            } else if (s.state === 'cancelled') {
              clearInterval(timer); this.analyze = { jobId: null, state: 'idle', progress: 0, message: '', error: '' }; resolve()
            }
          } catch (e) { /* 下次再试 */ }
        }, 800)
      })
    },

    // -------- 导出（从剪辑列表）--------
    async runExport({ merge = false, accurate = false, stretch = this.stretch169 } = {}) {
      if (!this.basket.length) return
      this.export = { jobId: null, state: 'running', progress: 0, message: '正在导出…', error: '', files: [], hasMerged: false }
      try {
        const clips = this.basket.map((b, i) => {
          const { start, end } = this.basketRange(b)
          return {
            upload_id: b.upload_id,
            kill_id: b.kill_id,
            label: b.label || `clip_${String(i + 1).padStart(2, '0')}`,
            start, end,
          }
        })
        const { job_id } = await api.startExport({ clips, merge, accurate, stretch_169: stretch })
        this.export.jobId = job_id
        await this._pollExport(job_id)
      } catch (e) {
        this.export.state = 'error'
        this.export.error = e?.response?.data?.detail || e.message || '导出失败'
      }
    },

    async _pollExport(jobId) {
      return new Promise((resolve) => {
        const timer = setInterval(async () => {
          try {
            const s = await api.exportStatus(jobId)
            this.export.progress = s.progress
            this.export.message = s.message
            this.export.state = s.state
            if (s.state === 'done') {
              clearInterval(timer); this.export.files = s.files || []; this.export.hasMerged = s.has_merged; resolve()
            } else if (s.state === 'error') {
              clearInterval(timer); this.export.error = s.error || '导出失败'; resolve()
            } else if (s.state === 'cancelled') {
              clearInterval(timer); this.export = { jobId: null, state: 'idle', progress: 0, message: '', error: '', files: [], hasMerged: false }; resolve()
            }
          } catch (e) {}
        }, 800)
      })
    },
  },
})
