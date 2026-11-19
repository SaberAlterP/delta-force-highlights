import { defineStore } from 'pinia'
import { mapi, errText } from './api'

const LS_PROJECT = 'df.montage.project'
const sleep = (ms) => new Promise(r => setTimeout(r, ms))
let patchTimer = null
let pendingPatch = {}

export const useMontage = defineStore('montage', {
  state: () => ({
    presets: null,
    settings: null,            // { model, api_key_set }
    projects: [],
    project: null,
    scan: null,                // { folder, items }
    scanning: false,
    source: null,              // 正在预览的素材 path（null = 看成片预览）
    T: 0,                      // 成片预览的播放头（秒）
    playing: false,
    selectedShot: null,
    jobs: { song: null, plan: null, render: null },   // { state, progress, message, error }
    error: '',
    notice: '',
  }),

  getters: {
    config: (s) => s.project?.config,
    timeline: (s) => s.project?.timeline,
    shots: (s) => s.project?.timeline?.shots || [],
    duration: (s) => s.project?.timeline?.duration || 0,
    song: (s) => s.project?.song,
    clipMap: (s) => Object.fromEntries((s.project?.clips || []).map(c => [c.path, c])),
    busy: (s) => Object.values(s.jobs).some(j => j && ['pending', 'running', 'cancelling'].includes(j.state)),
  },

  actions: {
    async init() {
      try {
        ;[this.presets, this.settings, this.projects] = await Promise.all([mapi.presets(), mapi.settings(), mapi.projects()])
        const last = localStorage.getItem(LS_PROJECT)
        const id = this.projects.find(p => p.id === last)?.id || this.projects[0]?.id
        if (id) await this.open(id)
        else await this.newProject()
      } catch (e) { this.error = errText(e, '集锦剪辑服务没有响应，请确认后端已更新并重启') }
    },
    async open(id) {
      await this.flush()
      this.project = await mapi.project(id)
      localStorage.setItem(LS_PROJECT, id)
      this.T = 0; this.selectedShot = null; this.source = null
      if (this.project.folder) this.rescan()
      else this.scan = null
    },
    async newProject() {
      const folder = this.project?.folder || await mapi.defaultFolder().catch(() => '')
      const p = await mapi.createProject({ folder })
      this.projects = await mapi.projects()
      await this.open(p.id)
    },
    async removeProject() {
      if (!this.project) return
      await mapi.remove(this.project.id)
      this.project = null
      this.projects = await mapi.projects()
      if (this.projects.length) await this.open(this.projects[0].id)
      else await this.newProject()
    },

    // 合并短时间内的多次修改，一次保存
    patch(values, delay = 400) {
      if (!this.project) return
      for (const [k, v] of Object.entries(values)) {
        if (k === 'settings') {
          pendingPatch.settings = pendingPatch.settings || {}
          for (const [sec, vals] of Object.entries(v)) pendingPatch.settings[sec] = { ...(pendingPatch.settings[sec] || {}), ...vals }
        } else pendingPatch[k] = v
      }
      clearTimeout(patchTimer)
      patchTimer = setTimeout(() => this.flush(), delay)
    },
    async flush() {
      clearTimeout(patchTimer)
      const values = pendingPatch
      pendingPatch = {}
      if (!this.project || !Object.keys(values).length) return
      try {
        const p = await mapi.patch(this.project.id, values)
        // 保存期间时间线可能被别的操作改过，只更新保存的字段
        this.project = { ...this.project, name: p.name, folder: p.folder, clips: p.clips, settings: p.settings, config: p.config }
        if ('name' in values) this.projects = await mapi.projects()
      } catch (e) { this.error = errText(e) }
    },
    setSetting(sec, key, value) {
      this.project.config[sec][key] = value
      this.patch({ settings: { [sec]: { [key]: value } } })
    },
    applyStyle(style) {
      for (const [sec, vals] of Object.entries(style.config)) Object.assign(this.project.config[sec], vals)
      this.patch({ settings: style.config }, 0)
      this.notice = `已套用「${style.label}」，点「自动编排」生效`
    },

    // -------- 素材
    async setFolder(folder) {
      if (!folder) return
      this.project.folder = folder
      this.patch({ folder }, 0)
      await this.rescan()
    },
    async rescan() {
      if (!this.project?.folder) return
      this.scanning = true; this.error = ''
      try { this.scan = await mapi.scan(this.project.folder) }
      catch (e) { this.scan = null; this.error = errText(e, '读取文件夹失败') }
      finally { this.scanning = false }
    },
    toggleClip(item, on) {
      const clips = [...(this.project.clips || [])]
      const i = clips.findIndex(c => c.path === item.path)
      if (i >= 0) clips[i] = { ...clips[i], selected: on }
      else if (on) clips.push({ path: item.path, name: item.name, duration: item.duration, selected: true, manual_kills: [] })
      this.project.clips = clips
      this.patch({ clips })
    },
    setManualKills(path, kills, item = null) {
      const clips = [...(this.project.clips || [])]
      const i = clips.findIndex(c => c.path === path)
      const sorted = [...kills].sort((a, b) => a - b).map(k => +k.toFixed(3))
      if (i >= 0) clips[i] = { ...clips[i], manual_kills: sorted, selected: true }
      else clips.push({ path, name: item?.name, duration: item?.duration, selected: true, manual_kills: sorted })
      this.project.clips = clips
      this.patch({ clips })
    },

    // -------- 后台任务
    async runJob(kind, start) {
      this.error = ''; this.notice = ''
      this.jobs[kind] = { state: 'pending', progress: 0, message: '' }
      try {
        await this.flush()
        const { job_id } = await start()
        this.jobs[kind].id = job_id
        for (;;) {
          await sleep(kind === 'render' ? 1000 : 500)
          const s = await mapi.job(job_id)
          this.jobs[kind] = { ...s, id: job_id }
          if (!['pending', 'running', 'cancelling'].includes(s.state)) break
        }
        if (this.jobs[kind].state === 'error') this.error = this.jobs[kind].error
        this.project = await mapi.project(this.project.id)
        return this.jobs[kind]
      } catch (e) { this.jobs[kind] = { state: 'error', error: errText(e) }; this.error = errText(e) }
    },
    async uploadSong(file) {
      const r = await this.runJob('song', () => mapi.uploadSong(this.project.id, file))
      if (r?.state === 'done') this.notice = `歌曲分析好了：${r.result.bpm} BPM。下一步点「自动编排」`
    },
    async autoPlan() {
      const r = await this.runJob('plan', () => mapi.plan(this.project.id))
      if (r?.state === 'done') {
        this.T = 0; this.selectedShot = null; this.source = null
        const sk = r.result.skipped || []
        this.notice = `编排好了：${r.result.shots} 个镜头，${r.result.duration.toFixed(1)} 秒` + (sk.length ? `；跳过 ${sk.length} 段没有击杀的素材` : '')
      }
    },
    async render() {
      const r = await this.runJob('render', () => mapi.render(this.project.id))
      if (r?.state === 'done') this.notice = `出片完成：${r.result.name}`
    },
    async cancelRender() { if (this.jobs.render?.id) await mapi.cancel(this.jobs.render.id) },

    // -------- 时间线
    async ops(list) {
      if (!this.project?.timeline) return
      try { this.project = await mapi.ops(this.project.id, list) }
      catch (e) { this.error = errText(e) }
    },
    nearestBeat(t, { downbeat = false, minT = -Infinity } = {}) {
      const arr = (downbeat ? this.song?.downbeats : this.song?.beats) || []
      let best = t, d = Infinity
      for (const b of arr) if (b > minT && Math.abs(b - t) < d) { d = Math.abs(b - t); best = b }
      return best
    },
    stepBeat(dir, downbeat = false) {
      const arr = (downbeat ? this.song?.downbeats : this.song?.beats) || []
      const eps = 0.02
      const next = dir > 0 ? arr.find(b => b > this.T + eps) : [...arr].reverse().find(b => b < this.T - eps)
      if (next != null) this.T = Math.max(0, Math.min(this.duration, next))
    },

    // -------- 助手
    async saveAgentSettings(values) { this.settings = await mapi.saveSettings(values) },
  },
})
