<script setup>
import { computed, ref } from 'vue'
import { useStore } from '../store'
import { api } from '../api'
import { recordedAt, statusInfo, killCount } from '../records'

const store = useStore()
const filter = ref('all')
const all = computed(() => (store.workflow?.records || []).filter(r => r.status !== 'removed')
  .sort((a, b) => recordedAt(b).localeCompare(recordedAt(a))))
const lists = computed(() => ({
  all: all.value.filter(r => r.status !== 'historical'),
  highlights: all.value.filter(r => r.result?.summary?.has_highlights),
  queue: all.value.filter(r => ['manual', 'waiting', 'processing', 'error', 'review'].includes(r.status)),
  history: all.value.filter(r => r.status === 'historical'),
}))
const shown = computed(() => lists.value[filter.value])
const manualCount = computed(() => all.value.filter(r => r.status === 'manual').length)
const starting = ref(false)
async function startAll() {
  starting.value = true
  try { await api.workflowStart(); await store.refreshWorkflow() } finally { starting.value = false }
}
const tabs = [['all', '全部'], ['highlights', '有集锦'], ['queue', '待处理'], ['history', '未处理的旧录像']]

const collapsed = defineModel('collapsed', { default: false })
const deleting = ref('')
const deleteError = ref('')
// 原片找不到且没有集锦包的局只剩一条记录，可直接移除
const orphan = (r) => r.status === 'missing' && !r.result?.bundle
const deletable = (r) => orphan(r) || (r.result?.bundle && !['waiting', 'processing'].includes(r.status))
// 和详情页一样：先卸下正在播放的素材，再删整个集锦包
async function removeBundle(r) {
  const ask = orphan(r)
    ? `移除 ${day(r)} 这一局的记录？

原片已经不在了，也没有集锦包，不会删除任何文件。`
    : `删除 ${day(r)} 这一局的整个集锦文件夹？

${r.result.bundle.path}

里面的整局原片、全部高光、手动剪辑和识别记录都会删除，无法恢复。`
  if (!confirm(ask)) return
  deleting.value = r.id; deleteError.value = ''
  try {
    store.forgetArchive(r.id, false)
    await new Promise(res => setTimeout(res, 300))
    await (orphan(r) ? api.workflowRemoveMissing(r.id) : api.workflowDeleteBundle(r.id))
    if (store.selectedRecordId === r.id) store.selectedRecordId = null
    await store.refreshWorkflow()
  } catch (e) { deleteError.value = e?.response?.data?.detail || e.message || '删除失败' }
  finally { deleting.value = '' }
}

function day(r) {
  const t = recordedAt(r)
  return t ? `${t.slice(5, 10).replace('-', '/')} ${t.slice(11, 16)}` : '时间未知'
}
</script>

<template>
  <aside class="games" :class="{ mini: collapsed }">
    <div class="bar">
      <div v-if="!collapsed" class="tabs" role="tablist">
        <button v-for="[key, label] in tabs" :key="key" role="tab" :aria-selected="filter === key"
                :class="{ on: filter === key }" @click="filter = key">
          {{ label }}<i v-if="lists[key].length">{{ lists[key].length }}</i>
        </button>
      </div>
      <button class="ghost fold" :title="collapsed ? '展开对局列表' : '收起对局列表'"
              :aria-label="collapsed ? '展开对局列表' : '收起对局列表'" @click="collapsed = !collapsed">{{ collapsed ? '»' : '«' }}</button>
    </div>
    <template v-if="!collapsed">
      <div v-if="manualCount" class="start-all">
        <span>{{ manualCount }} 局等你开始</span>
        <button class="primary" :disabled="starting" @click="startAll">全部开始处理</button>
      </div>
      <div v-if="store.workflow?.paused" class="paused">⏸ {{ store.workflow.paused }}</div>
      <p v-if="deleteError" class="del-error" role="alert">{{ deleteError }}</p>
    </template>
    <div class="list">
      <div v-for="r in shown" :key="r.id" class="game" :class="{ on: store.selectedRecordId === r.id }">
        <button class="pick" :title="collapsed ? `${day(r)} · ${statusInfo(r).label}` : ''" @click="store.selectedRecordId = r.id">
          <span class="kills" :class="{ hot: r.result?.summary?.has_highlights }">{{ killCount(r) ?? '–' }}</span>
          <template v-if="!collapsed">
            <span class="meta">
              <b>{{ day(r) }}</b>
              <small :class="statusInfo(r).tone">{{ statusInfo(r).label }}</small>
            </span>
            <span v-if="r.result?.files?.length" class="clips">{{ r.result.files.length }} 段</span>
          </template>
          <i v-if="r.status === 'processing'" class="spin" aria-label="正在处理"></i>
        </button>
        <button v-if="!collapsed && deletable(r)" class="danger ghost del" :disabled="!!deleting"
                :title="orphan(r) ? '移除这条记录' : '删除这一局的集锦包'" :aria-label="`${orphan(r) ? '移除' : '删除'} ${day(r)} 的${orphan(r) ? '记录' : '集锦包'}`" @click="removeBundle(r)">
          {{ deleting === r.id ? '…' : '✕' }}
        </button>
      </div>
      <p v-if="!shown.length && !collapsed" class="empty">
        <template v-if="!store.workflow">正在连接本地后台…</template>
        <template v-else-if="filter === 'history'">没有未处理的旧录像。</template>
        <template v-else-if="!store.workflow.settings.enabled">自动监控已暂停，打完一局后不会自动处理。<br>可在右上角「设置」里开启。</template>
        <template v-else>还没有对局。打完一局后，录像写完约 2 分钟会自动出现在这里。</template>
      </p>
    </div>
  </aside>
</template>

<style scoped>
.games { display: flex; flex-direction: column; min-height: 0; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.bar { display: flex; align-items: flex-start; gap: 4px; padding: 10px; border-bottom: 1px solid var(--border); }
.tabs { flex: 1; display: flex; flex-wrap: wrap; gap: 4px; }
.fold { flex: none; padding: 4px 9px; font-size: 13px; line-height: 1.2; color: var(--muted); }
.mini .bar { justify-content: center; padding: 10px 6px; }
.del-error { margin: 0; padding: 7px 10px; font-size: 11px; line-height: 1.6; color: #f0a6a8; background: #2a1718; border-bottom: 1px solid var(--border); }
.tabs button { padding: 5px 9px; font-size: 12px; background: transparent; border-color: transparent; color: var(--muted); border-radius: 6px; }
.tabs button.on { color: var(--text); background: var(--panel-2); border-color: var(--border); }
.tabs i { font-style: normal; margin-left: 5px; font-size: 10px; color: var(--accent); }
.start-all { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 12px; color: var(--accent); }
.start-all button { padding: 5px 10px; font-size: 12px; }
.paused { padding: 7px 10px; font-size: 11px; line-height: 1.6; color: var(--accent); background: #f5a6230d; border-bottom: 1px solid var(--border); }
.list { overflow-y: auto; padding: 6px; display: flex; flex-direction: column; gap: 4px; }
.game { position: relative; border: 1px solid transparent; border-radius: 8px; }
.game:hover { background: var(--panel-2); }
.game.on { background: var(--panel-2); border-color: var(--accent); }
.pick { width: 100%; display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 10px; text-align: left; padding: 9px 10px; background: transparent; border: 0; border-radius: 8px; position: relative; }
.pick:hover:not(:disabled) { background: transparent; }
.mini .pick { grid-template-columns: 1fr; padding: 9px 0; }
.del { position: absolute; top: 4px; right: 4px; padding: 1px 7px; font-size: 12px; color: var(--danger); background: var(--panel); border-color: #46282b; opacity: 0; transition: opacity .12s; }
.mini .list { scrollbar-width: none; }
.game:hover .del, .del:focus-visible, .del:disabled { opacity: 1; }
.game:hover .clips { visibility: hidden; }
.kills { font: 600 22px/1 Consolas, monospace; color: var(--muted); text-align: center; }
.kills.hot { color: var(--accent); }
.meta { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.meta b { font-weight: 500; font-size: 13px; font-variant-numeric: tabular-nums; }
.meta small { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta small.ok { color: var(--ok); } .meta small.warn { color: var(--accent); } .meta small.bad { color: var(--danger); }
.clips { font-size: 11px; color: var(--accent); background: #f5a62314; border: 1px solid #f5a62340; padding: 2px 6px; border-radius: 999px; }
.spin { position: absolute; right: 10px; top: 50%; width: 12px; height: 12px; margin-top: -6px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty { color: var(--muted); font-size: 12px; line-height: 1.8; text-align: center; padding: 28px 12px; margin: 0; }
</style>
