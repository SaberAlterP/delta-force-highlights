<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api'
import { useStore } from '../store'
import { recordedAt, statusInfo, killCount } from '../records'
import VideoPlayer from './VideoPlayer.vue'
import ClipTimeline from './ClipTimeline.vue'
import KillList from './KillList.vue'
import ExportPanel from './ExportPanel.vue'

const store = useStore()
const busy = ref(false)
const message = ref('')
const error = ref('')
const manualPlay = ref(null)

const record = computed(() => store.workflow?.records.find(r => r.id === store.selectedRecordId) || null)
const result = computed(() => record.value?.result || null)
const summary = computed(() => result.value?.summary || null)
const finished = computed(() => record.value && ['ready', 'no_highlights', 'review', 'deleted'].includes(record.value.status))
const idle = computed(() => record.value && !['waiting', 'processing'].includes(record.value.status))
const active = computed(() => store.workflow?.active?.id === record.value?.id ? store.workflow.active : null)
const editingThis = computed(() => store.video?.workflow_id && store.video.workflow_id === record.value?.id)
const manualVideo = computed(() => store.video && !store.video.workflow_id)

const sources = computed(() => {
  if (!record.value || !finished.value) return []
  const list = []
  if (record.value.original_available) list.push({ key: 'bundle_' + record.value.id, label: '整局原片', index: null })
  ;(result.value?.files || []).forEach((f, i) => list.push({ key: `bundle_${record.value.id}_clip_${f.sha256?.slice(0, 12)}`, label: `高光 ${i + 1}`, index: i }))
  return list
})

function title(r) {
  const t = recordedAt(r)
  if (!t) return '对局'
  const d = new Date(t)
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${t.slice(11, 16)}`
}
function due(v) { return new Date(v * 1000).toLocaleString('zh-CN', { hour12: false, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }

async function open(source) {
  error.value = ''; manualPlay.value = null
  try {
    await store.openArchiveVideo(record.value.id, source.index)
    await nextTick()
  } catch (e) { error.value = e?.response?.data?.detail || '无法载入这段素材' }
}

// 选中一局时自动载入：有高光先看高光 1，否则整局
watch(() => [record.value?.id, sources.value.length], ([id]) => {
  if (!id || editingThis.value || !sources.value.length) return
  open(sources.value.find(s => s.index === 0) || sources.value[0])
}, { immediate: true })

async function act(fn, done) {
  busy.value = true; error.value = ''; message.value = ''
  try { await fn(); message.value = done || ''; await store.refreshWorkflow() }
  catch (e) { error.value = e?.response?.data?.detail || e.message || '操作失败' }
  finally { busy.value = false }
}
// 先卸下播放器，让浏览器停止读取这段素材，再请求删除
async function release(originalOnly) {
  manualPlay.value = null
  store.forgetArchive(record.value.id, originalOnly)
  await nextTick()
  await new Promise(r => setTimeout(r, 300))
}
function removeOriginal() {
  if (!confirm(`删除这局的整局原录像？\n\n高光、手动剪辑和识别记录都会保留。\n原片删除后无法恢复。`)) return
  act(async () => { await release(true); await api.workflowDeleteOriginal(record.value.id) }, '整局原片已删除')
}
function removeBundle() {
  if (!confirm(`删除这一局的整个集锦文件夹？\n\n${result.value.bundle.path}\n\n里面的整局原片、全部高光、手动剪辑和识别记录都会删除，无法恢复。`)) return
  const id = record.value.id
  act(async () => { await release(false); await api.workflowDeleteBundle(id); store.selectedRecordId = null }, '')
}
</script>

<template>
  <section class="detail">
    <!-- 手动上传的录像 -->
    <header v-if="!record && manualVideo" class="head">
      <div>
        <span class="eyebrow">手动识别</span>
        <h1>{{ store.video.filename }}</h1>
        <p class="sub">上传的录像只在本工具缓存里，七天未使用会自动清理。</p>
      </div>
      <button class="ghost" @click="store.panel = 'manual'">换一段录像</button>
    </header>

    <template v-else-if="record">
      <header class="head">
        <div class="head-main">
          <span class="eyebrow" :class="statusInfo(record).tone">{{ statusInfo(record).label }}</span>
          <h1>{{ title(record) }}</h1>
          <p v-if="summary" class="sub">
            <b class="kills">{{ killCount(record) }}</b> {{ summary.official_kills != null ? '杀（官方结算）' : '杀（画面识别）' }}
            <template v-if="result.official_events"> · 核对到 {{ summary.confirmed_kills }} 名不同干员 · 摸金 {{ summary.loot_points }} 次</template>
            · {{ result.files.length ? `${result.files.length} 段集锦` : `没有 ${store.workflow.settings.window_seconds} 秒内 ${store.workflow.settings.min_operators} 杀的片段` }}
          </p>
          <p v-else class="sub muted">{{ record.path }}</p>
        </div>
        <div class="head-actions">
          <button v-if="result?.bundle" class="ghost" @click="act(() => api.workflowOpenFolder(record.id))">打开文件夹</button>
          <button v-if="record.status === 'historical'" class="primary" :disabled="busy" @click="act(() => api.workflowRetry(record.id), '已加入处理队列，原片保留')">处理这局</button>
          <button v-if="['error', 'review', 'no_highlights', 'ready'].includes(record.status)" class="ghost" :disabled="busy" @click="act(() => api.workflowRetry(record.id), '已重新加入队列')">重新识别</button>
        </div>
      </header>

      <div v-if="active" class="notice live" role="status">
        <div class="progress"><i :style="{ width: `${active.progress * 100}%` }"></i></div>
        <span>{{ active.message }}</span>
      </div>
      <p v-else-if="record.status === 'waiting'" class="notice">排队中，前面的录像处理完就轮到它。</p>
      <p v-if="record.error && record.status !== 'waiting'" class="notice" :class="{ bad: record.status === 'error' }">{{ record.error }}</p>
      <p v-if="result?.official_events?.warnings?.length" class="notice">{{ result.official_events.warnings.join('；') }}</p>

      <div v-if="sources.length" class="sources" role="tablist">
        <button v-for="s in sources" :key="s.key" role="tab" :aria-selected="store.video?.upload_id === s.key"
                :class="{ on: store.video?.upload_id === s.key && !manualPlay }" @click="open(s)">{{ s.label }}</button>
        <template v-for="job in record.manual_exports || []" :key="job.id">
          <button v-for="f in job.files" :key="f.path" :class="{ on: manualPlay?.name === f.name }"
                  :title="'手动剪辑：' + f.name" @click="manualPlay = { name: f.name, src: api.workflowManualFileUrl(record.id, job.id, f.name) }">✂ {{ f.name }}</button>
        </template>
      </div>
    </template>

    <div v-else class="welcome">
      <h1>选择左边的一局</h1>
      <p>每一局打完后，工具会自动找出 {{ store.workflow?.settings.window_seconds || 90 }} 秒内 {{ store.workflow?.settings.min_operators || 2 }} 杀以上的片段，
        把整局原片和高光放进同一个文件夹。</p>
      <button class="ghost" @click="store.panel = 'guide'">第一次用？看使用指南</button>
    </div>

    <p v-if="error" class="notice bad" role="alert">{{ error }}</p>
    <p v-if="message" class="notice ok" role="status">{{ message }}</p>

    <!-- 播放 / 剪辑 -->
    <div v-if="manualPlay" class="manual-play">
      <video :key="manualPlay.src" :src="manualPlay.src" controls autoplay></video>
    </div>
    <template v-else-if="store.video && (editingThis || (!record && manualVideo))">
      <p v-if="store.projectSaveError" class="notice bad">{{ store.projectSaveError }}</p>
      <VideoPlayer />
      <ClipTimeline />
      <div class="work">
        <KillList />
        <ExportPanel />
      </div>
      <p v-if="editingThis" class="foot muted">标记的修改会自动存回这局的文件夹（{{ store.projectSaveStatus || '剪辑工程.json' }}）。手动导出的片段保存在文件夹里的「手动剪辑」。</p>
    </template>

    <!-- 原片保留与删除 -->
    <footer v-if="record && finished" class="keep">
      <div>
        <b>原片</b>
        <span v-if="record.status === 'deleted'">已删除，高光和记录仍保留。</span>
        <span v-else-if="result?.cleanup_after && record.allow_cleanup">{{ due(result.cleanup_after) }} 自动删除，省出硬盘空间。</span>
        <span v-else>一直保留，不会自动删除。</span>
      </div>
      <div class="keep-actions">
        <button v-if="record.original_available && record.allow_cleanup && result?.cleanup_after" class="ghost" :disabled="busy" @click="act(() => api.workflowRetain(record.id), '这局原片会一直保留')">一直保留原片</button>
        <button v-if="record.original_available && idle" class="danger" :disabled="busy" @click="removeOriginal">删除原片</button>
        <button v-if="result?.bundle && idle" class="danger" :disabled="busy" @click="removeBundle">删除整个集锦包</button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
.head-main { min-width: 0; }
.eyebrow { font-size: 12px; color: var(--muted); letter-spacing: .5px; }
.eyebrow.ok { color: var(--ok); } .eyebrow.warn { color: var(--accent); } .eyebrow.bad { color: var(--danger); }
h1 { margin: 4px 0 6px; font-size: 24px; font-weight: 600; letter-spacing: .5px; }
.sub { margin: 0; font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
.sub .kills { font: 600 18px Consolas, monospace; color: var(--accent); }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.notice { margin: 0; padding: 9px 12px; font-size: 12px; line-height: 1.7; color: var(--muted); background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 6px; overflow-wrap: anywhere; }
.notice.bad { border-left-color: var(--danger); color: #f0a6a8; }
.notice.ok { border-left-color: var(--ok); color: var(--ok); }
.notice.live { display: flex; align-items: center; gap: 12px; }
.notice.live .progress { flex: 0 0 160px; }
.sources { display: flex; gap: 6px; flex-wrap: wrap; }
.sources button { font-size: 12px; padding: 6px 12px; border-radius: 999px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sources button.on { background: var(--accent); border-color: var(--accent); color: #1a1205; font-weight: 600; }
.welcome { padding: 60px 24px; text-align: center; background: var(--panel); border: 1px dashed var(--border); border-radius: var(--radius); }
.welcome h1 { font-size: 20px; } .welcome p { color: var(--muted); font-size: 13px; line-height: 1.9; max-width: 460px; margin: 10px auto 18px; }
.manual-play video { display: block; width: min(100%, calc(65vh * 16 / 9)); margin: 0 auto; background: #000; border-radius: 8px; }
.work { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(300px, 1fr); gap: 12px; align-items: start; }
.foot { font-size: 11px; margin: 0; }
.keep { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 14px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); font-size: 12px; }
.keep b { margin-right: 10px; } .keep span { color: var(--muted); }
.keep-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.keep-actions button { font-size: 12px; padding: 6px 12px; }
@media (max-width: 1280px) { .work { grid-template-columns: 1fr; } }
</style>
