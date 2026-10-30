import axios from 'axios'

const http = axios.create({ baseURL: '/api/montage' })
const data = r => r.data

export const mapi = {
  presets: () => http.get('/presets').then(data),
  settings: () => http.get('/settings').then(data),
  saveSettings: (values) => http.post('/settings', values).then(data),
  defaultFolder: () => http.get('/default-folder').then(r => r.data.path),
  scan: (folder) => http.post('/scan', { folder }, { timeout: 0 }).then(data),
  fileUrl: (path) => `/api/montage/file?path=${encodeURIComponent(path)}`,
  thumbUrl: (path, t = 2) => `/api/montage/thumb?path=${encodeURIComponent(path)}&t=${t.toFixed(1)}`,
  uploadBumper: (kind, file) => { const f = new FormData(); f.append('file', file); return http.post(`/bumpers/${kind}`, f, { timeout: 0 }).then(data) },

  projects: () => http.get('/projects').then(data),
  createProject: (values) => http.post('/projects', values).then(data),
  project: (id) => http.get(`/projects/${id}`).then(data),
  patch: (id, values) => http.patch(`/projects/${id}`, values).then(data),
  remove: (id) => http.delete(`/projects/${id}`).then(data),
  uploadSong: (id, file) => { const f = new FormData(); f.append('file', file); return http.post(`/projects/${id}/song`, f, { timeout: 0 }).then(data) },
  songUrl: (id, v = '') => `/api/montage/projects/${id}/song/audio?v=${encodeURIComponent(v)}`,
  plan: (id) => http.post(`/projects/${id}/plan`).then(data),
  ops: (id, ops) => http.post(`/projects/${id}/ops`, { ops }).then(data),
  render: (id) => http.post(`/projects/${id}/render`).then(data),
  job: (jobId) => http.get(`/jobs/${jobId}`).then(data),
  cancel: (jobId) => http.post(`/jobs/${jobId}/cancel`).then(data),
  agent: (id, text) => http.post(`/projects/${id}/agent`, { text }, { timeout: 0 }).then(data),
  agentReset: (id) => http.post(`/projects/${id}/agent/reset`).then(data),
}

export const errText = (e, fallback = '操作失败') => e?.response?.data?.detail || e?.message || fallback
