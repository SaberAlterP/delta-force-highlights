// 视频压缩：全页共享一份状态，抽屉关掉后压缩照常进行，顶部按钮显示进度。
import axios from 'axios'
import { reactive } from 'vue'

const http = axios.create({ baseURL: '/api/compress' })
const data = r => r.data

export const capi = {
  presets: () => http.get('/presets').then(data),
  pickFile: () => http.post('/pick-file', {}, { timeout: 0 }).then(data),
  probe: (source) => http.post('/probe', source).then(data),
  start: (source, preset, targetMb, name) => http.post('', { source, preset, target_mb: targetMb, name }).then(data),
  status: (jobId) => http.get(`/${jobId}`).then(data),
  cancel: (jobId) => http.post(`/${jobId}/cancel`).then(data),
  openFolder: (jobId) => http.post(`/${jobId}/open-folder`).then(data),
  fileUrl: (jobId, download = false) => `/api/compress/${jobId}/file${download ? '?download=1' : ''}`,
}

export const compress = reactive({
  source: null,      // { kind, ... } 交给后端定位文件
  label: '',         // 给人看的来源名，例如「高光 2」
  info: null,        // { name, size, duration, width, height, fps }
  infoError: '',
  jobId: null,
  state: 'idle',     // idle / running / done / error / cancelled
  progress: 0,
  message: '',
  error: '',
  result: null,
})

let timer = null
const busy = () => ['pending', 'running', 'cancelling'].includes(compress.state)
export const isBusy = busy

const STALE = '后台还是旧版本，没有压缩功能：请关掉剪辑工具后重新双击「启动剪辑工具」再试'
// 前端更新了但后端没重启时，/api/compress 会落到静态文件上，得到 405 / 404 Not Found
export const errText = (e, fallback = '操作失败') => {
  const status = e?.response?.status, detail = e?.response?.data?.detail
  if (status === 405 || (status === 404 && detail === 'Not Found')) return STALE
  return detail || e?.message || fallback
}

/** 选定要压缩的视频；正在压缩时不换（避免把进度丢掉）。 */
export async function setSource(source, label = '') {
  if (busy()) return false
  Object.assign(compress, { source, label, info: null, infoError: '', jobId: null, state: 'idle',
    progress: 0, message: '', error: '', result: null })
  if (!source) return true
  try { compress.info = await capi.probe(source) }
  catch (e) { compress.infoError = errText(e, '读不到这个视频') }
  return true
}

export async function pickFile() {
  const r = await capi.pickFile()
  if (!r.path) return false
  await setSource({ kind: 'picked', path: r.path }, r.info?.name || r.path)
  return true
}

export async function start(preset, targetMb) {
  compress.error = ''; compress.result = null
  try {
    const { job_id } = await capi.start(compress.source, preset, targetMb, compress.label)
    Object.assign(compress, { jobId: job_id, state: 'running', progress: 0, message: '准备压缩…' })
    poll()
  } catch (e) { compress.error = errText(e, '无法开始压缩') }
}

function poll() {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    try {
      const s = await capi.status(compress.jobId)
      Object.assign(compress, { state: s.state, progress: s.progress, message: s.message })
      if (s.state === 'done') compress.result = s.result
      else if (s.state === 'error') compress.error = s.error || '压缩失败'
      else if (s.state === 'cancelled') compress.message = '已取消'
      if (busy()) poll()
    } catch (e) {
      compress.state = 'error'; compress.error = errText(e, '后台没有响应，可能已重启')
    }
  }, 700)
}

export async function cancel() {
  if (compress.jobId) await capi.cancel(compress.jobId).catch(() => {})
}

export function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(2) + ' GB'
  if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(1) + ' MB'
  return Math.max(1, Math.round(bytes / 1024)) + ' KB'
}

export function fmtDuration(sec) {
  sec = Math.round(sec || 0)
  const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}
