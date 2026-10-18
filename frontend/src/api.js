import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

const CHUNK_SIZE = 16 * 1024 * 1024 // 16MB：分片越大→请求数越少→大文件越稳

// 带指数退避重试的 POST。
// localhost 上传大文件时偶发的瞬时断连会让 axios 抛 "Network Error"，
// 不重试就会让整次上传前功尽弃；分片写入是按 index 覆盖的，重试天然幂等。
async function postWithRetry(url, form, { retries = 4, baseDelay = 500 } = {}) {
  let lastErr
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await http.post(url, form, { timeout: 0 })
    } catch (e) {
      lastErr = e
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, baseDelay * 2 ** attempt))
      }
    }
  }
  throw lastErr
}

export const api = {
  health: () => http.get('/health').then(r => r.data),
  getConfig: () => http.get('/config').then(r => r.data),
  workflowStatus: () => http.get('/workflow').then(r => r.data),
  workflowSettings: (values) => http.post('/workflow/settings', values).then(r => r.data),
  workflowRetry: (id) => http.post(`/workflow/retry/${id}`).then(r => r.data),
  workflowFileUrl: (id, index) => `/api/workflow/${id}/file/${index}`,
  workflowOriginalUrl: (id) => `/api/workflow/${id}/original`,
  workflowOpenFolder: (id) => http.post('/workflow/open-folder', { record_id: id }).then(r => r.data),
  workflowNotificationTest: () => http.post('/workflow/notification-test').then(r => r.data),
  workflowCleanupCache: () => http.post('/workflow/cache/cleanup').then(r => r.data),
  workflowRetain: (id) => http.post(`/workflow/${id}/retain`).then(r => r.data),
  workflowEnvironment: () => http.get('/workflow/environment').then(r => r.data),
  pickFolder: (initial, title) => http.post('/workflow/pick-folder', { initial, title }, { timeout: 0 }).then(r => r.data.path),
  workflowDeleteOriginal: (id) => http.post(`/workflow/${id}/delete-original`).then(r => r.data),
  workflowDeleteBundle: (id) => http.post(`/workflow/${id}/delete-bundle`).then(r => r.data),
  workflowEdit:(id, clipIndex = null) => http.post(`/workflow/${id}/edit`, { clip_index: clipIndex }).then(r => r.data),
  workflowSaveProject: (id, sourceId, kills) => http.post(`/workflow/${id}/project`, { source_id: sourceId, kills }).then(r => r.data),
  workflowManualFileUrl: (id, exportId, name) => `/api/workflow/${id}/manual/${exportId}/${encodeURIComponent(name)}`,

  /**
   * 分片上传视频（每片自动重试，适配 ~4GB 大文件）。
   * @param {File} file
   * @param {(percent:number)=>void} onProgress 0~100
   * @returns {Promise<object>} VideoMeta
   */
  async uploadVideo(file, onProgress) {
    // Vite 在后端离线时会把代理连接失败包装成 HTTP 500；上传前单独探活，
    // 给出可执行的本地恢复提示，避免用户误以为视频文件损坏。
    try {
      await http.get('/health', { timeout: 2500 })
    } catch (_error) {
      throw new Error('本地后端未启动，请双击「三角洲击杀剪辑工具」重新启动后再上传')
    }

    const totalChunks = Math.ceil(file.size / CHUNK_SIZE)

    const initForm = new FormData()
    initForm.append('filename', file.name)
    initForm.append('total_chunks', String(totalChunks))
    const { upload_id } = (await postWithRetry('/upload/init', initForm)).data

    for (let i = 0; i < totalChunks; i++) {
      const start = i * CHUNK_SIZE
      const blob = file.slice(start, start + CHUNK_SIZE)
      const form = new FormData()
      form.append('upload_id', upload_id)
      form.append('index', String(i))
      form.append('chunk', blob, `${i}.part`)
      await postWithRetry('/upload/chunk', form)
      if (onProgress) onProgress(Math.round(((i + 1) / totalChunks) * 100))
    }

    const doneForm = new FormData()
    doneForm.append('upload_id', upload_id)
    const meta = (await postWithRetry('/upload/complete', doneForm, { retries: 2 })).data
    return meta
  },

  videoUrl: (uploadId) => `/api/video/${uploadId}`,

  startAnalyze: (payload) => http.post('/analyze', payload).then(r => r.data),
  analyzeStatus: (jobId) => http.get(`/analyze/${jobId}`).then(r => r.data),

  startExport: (payload) => http.post('/export', payload).then(r => r.data),
  exportStatus: (jobId) => http.get(`/export/${jobId}`).then(r => r.data),
  exportFileUrl: (jobId, name) => `/api/export/${jobId}/file/${encodeURIComponent(name)}`,
  exportMergedUrl: (jobId) => `/api/export/${jobId}/merged`,
  exportZipUrl: (jobId) => `/api/export/${jobId}/zip`,

  storageUsage: () => http.get('/storage/usage').then(r => r.data),
  storageFiles: (target) => http.get('/storage/files', { params: { target } }).then(r => r.data),
  storageFileUrl: (target, path) => {
    const safePath = path.split('/').map(encodeURIComponent).join('/')
    return `/api/storage/file/${encodeURIComponent(target)}/${safePath}`
  },
  storageDelete: (target, path) => http.post('/storage/delete', { target, path }).then(r => r.data),
  storageRestoreUpload: (path, filename) => http.post('/storage/restore-upload', { path, filename }).then(r => r.data),
  storageCleanup: (targets, force = false) => http.post('/storage/cleanup', { targets, force }).then(r => r.data),
}
