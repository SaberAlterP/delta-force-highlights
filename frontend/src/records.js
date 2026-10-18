// 工作流记录的展示辅助：录制时间、状态文案、击杀数。

export function recordedAt(r) {
  if (r.result?.bundle?.recorded_at) return r.result.bundle.recorded_at
  const m = /record(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/i.exec(r.path || '')
  return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}` : ''
}

export function killCount(r) {
  const s = r.result?.summary
  return s ? (s.official_kills ?? s.confirmed_kills) : null
}

const STATUS = {
  historical: ['未处理的旧录像', ''],
  waiting: ['排队中', 'warn'],
  processing: ['正在识别…', 'warn'],
  ready: ['有集锦', 'ok'],
  no_highlights: ['无集锦', ''],
  deleted: ['原片已删除 · 高光保留', ''],
  review: ['需要检查', 'warn'],
  error: ['处理失败', 'bad'],
  missing: ['原片找不到了', 'bad'],
}

export function statusInfo(r) {
  const [label, tone] = STATUS[r.status] || [r.status, '']
  if (r.status === 'deleted' && r.result?.summary?.has_highlights) return { label: '有集锦 · 原片已删除', tone: 'ok' }
  return { label, tone }
}
