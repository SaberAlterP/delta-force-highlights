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

function day(r) {
  const t = recordedAt(r)
  return t ? `${t.slice(5, 10).replace('-', '/')} ${t.slice(11, 16)}` : '时间未知'
}
</script>

<template>
  <aside class="games">
    <div class="tabs" role="tablist">
      <button v-for="[key, label] in tabs" :key="key" role="tab" :aria-selected="filter === key"
              :class="{ on: filter === key }" @click="filter = key">
        {{ label }}<i v-if="lists[key].length">{{ lists[key].length }}</i>
      </button>
    </div>
    <div v-if="manualCount" class="start-all">
      <span>{{ manualCount }} 局等你开始</span>
      <button class="primary" :disabled="starting" @click="startAll">全部开始处理</button>
    </div>
    <div v-if="store.workflow?.paused" class="paused">⏸ {{ store.workflow.paused }}</div>
    <div class="list">
      <button v-for="r in shown" :key="r.id" class="game" :class="{ on: store.selectedRecordId === r.id }"
              @click="store.selectedRecordId = r.id">
        <span class="kills" :class="{ hot: r.result?.summary?.has_highlights }">{{ killCount(r) ?? '–' }}</span>
        <span class="meta">
          <b>{{ day(r) }}</b>
          <small :class="statusInfo(r).tone">{{ statusInfo(r).label }}</small>
        </span>
        <span v-if="r.result?.files?.length" class="clips">{{ r.result.files.length }} 段</span>
        <i v-if="r.status === 'processing'" class="spin" aria-label="正在处理"></i>
      </button>
      <p v-if="!shown.length" class="empty">
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
.tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 10px; border-bottom: 1px solid var(--border); }
.tabs button { padding: 5px 9px; font-size: 12px; background: transparent; border-color: transparent; color: var(--muted); border-radius: 6px; }
.tabs button.on { color: var(--text); background: var(--panel-2); border-color: var(--border); }
.tabs i { font-style: normal; margin-left: 5px; font-size: 10px; color: var(--accent); }
.start-all { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--border); font-size: 12px; color: var(--accent); }
.start-all button { padding: 5px 10px; font-size: 12px; }
.paused { padding: 7px 10px; font-size: 11px; line-height: 1.6; color: var(--accent); background: #f5a6230d; border-bottom: 1px solid var(--border); }
.list { overflow-y: auto; padding: 6px; display: flex; flex-direction: column; gap: 4px; }
.game { display: grid; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 10px; text-align: left; padding: 9px 10px; background: transparent; border: 1px solid transparent; border-radius: 8px; position: relative; }
.game:hover:not(:disabled) { background: var(--panel-2); border-color: transparent; }
.game.on { background: var(--panel-2); border-color: var(--accent); }
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
