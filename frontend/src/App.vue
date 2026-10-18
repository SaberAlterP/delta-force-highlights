<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useStore } from './store'
import GameList from './components/GameList.vue'
import GameDetail from './components/GameDetail.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import GuidePanel from './components/GuidePanel.vue'
import UploadPanel from './components/UploadPanel.vue'
import AnalyzePanel from './components/AnalyzePanel.vue'

const store = useStore()
let timer
const settings = computed(() => store.workflow?.settings)
const ready = computed(() => settings.value && settings.value.player_id && settings.value.watch_root && settings.value.output_root)
const queued = computed(() => (store.workflow?.records || []).filter(r => ['waiting', 'processing'].includes(r.status)).length)
const titles = { settings: '设置', guide: '使用指南', manual: '手动识别录像' }

function onKey(e) { if (e.key === 'Escape') store.panel = '' }
onMounted(async () => {
  store.loadConfig()
  await store.refreshWorkflow()
  // 第一次打开、还没填设置时直接给出指南
  if (store.workflow && !ready.value) store.panel = 'guide'
  timer = setInterval(() => store.refreshWorkflow(), 4000)
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => { clearInterval(timer); window.removeEventListener('keydown', onKey) })
watch(() => store.workflow?.settings.player_id, (id) => { if (id && !store.playerId) store.setPlayerId(id) })
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <span class="mark">▲</span>
        <div><b>三角洲 · 多杀集锦</b><small>打完一局，自动剪好高光</small></div>
      </div>
      <button v-if="settings" class="status" :class="{ live: settings.enabled && ready }" @click="store.panel = 'settings'"
              :title="store.workflow.paused || (settings.enabled ? '点击打开设置' : '自动监控已暂停，点击打开设置')">
        <i></i>
        <template v-if="!ready">还没设置好</template>
        <template v-else-if="!settings.enabled">监控已暂停</template>
        <template v-else-if="store.workflow.active">正在处理 {{ Math.round(store.workflow.active.progress * 100) }}%</template>
        <template v-else-if="store.workflow.paused">⏸ 暂停中</template>
        <template v-else>监控中</template>
        <span v-if="queued > 1" class="q">队列 {{ queued }}</span>
      </button>
      <span class="spacer"></span>
      <nav>
        <button class="ghost" @click="store.panel = 'manual'">手动识别</button>
        <button class="ghost" @click="store.panel = 'guide'">使用指南</button>
        <button :class="ready ? 'ghost' : 'primary'" @click="store.panel = 'settings'">设置</button>
      </nav>
    </header>
    <p v-if="store.workflowError" class="offline" role="alert">{{ store.workflowError }}</p>
    <p v-else-if="store.workflow?.error" class="offline" role="alert">后台提示：{{ store.workflow.error }}</p>

    <main class="layout">
      <GameList />
      <GameDetail />
    </main>

    <Transition name="drawer">
      <div v-if="store.panel" class="scrim" @click.self="store.panel = ''">
        <aside class="drawer" role="dialog" :aria-label="titles[store.panel]">
          <header><h2>{{ titles[store.panel] }}</h2><button class="ghost close" aria-label="关闭" @click="store.panel = ''">✕</button></header>
          <div class="drawer-body">
            <SettingsPanel v-if="store.panel === 'settings'" />
            <GuidePanel v-else-if="store.panel === 'guide'" />
            <div v-else-if="store.panel === 'manual'" class="manual">
              <p class="muted">不在录像文件夹里的视频，可以上传到这里识别和剪辑。上传的文件只存在工具缓存里。</p>
              <UploadPanel />
              <AnalyzePanel v-if="store.video && !store.video.workflow_id" />
              <button v-if="store.video && !store.video.workflow_id" class="primary" @click="store.panel = ''">去剪辑这段录像</button>
            </div>
          </div>
        </aside>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.app { min-height: 100%; display: flex; flex-direction: column; }
.topbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 16px; padding: 10px 18px; border-bottom: 1px solid var(--border); background: #12161dee; backdrop-filter: blur(8px); }
.brand { display: flex; align-items: center; gap: 10px; }
.brand b { display: block; font-size: 15px; letter-spacing: .5px; } .brand small { color: var(--muted); font-size: 11px; }
.mark { font-size: 24px; color: var(--accent); filter: drop-shadow(0 0 8px #f5a62380); }
.status { display: flex; align-items: center; gap: 7px; font-size: 12px; padding: 5px 11px; border-radius: 999px; color: var(--muted); background: var(--panel); }
.status i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.status.live { color: var(--ok); } .status.live i { background: var(--ok); box-shadow: 0 0 0 3px #3fb95026; animation: pulse 2s infinite; }
.status .q { color: var(--accent); margin-left: 4px; }
@keyframes pulse { 50% { box-shadow: 0 0 0 6px #3fb95000; } }
.spacer { flex: 1; }
nav { display: flex; gap: 6px; } nav button { font-size: 13px; padding: 7px 14px; }
.offline { margin: 10px 18px 0; padding: 8px 12px; font-size: 12px; color: #f0a6a8; background: #2a1718; border: 1px solid #46282b; border-radius: 6px; }
.layout { flex: 1; display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 14px; padding: 14px 18px; align-items: start; }
.layout > :first-child { position: sticky; top: 70px; max-height: calc(100vh - 86px); }
.scrim { position: fixed; inset: 0; z-index: 50; background: #05080cb3; display: flex; justify-content: flex-end; }
.drawer { width: min(520px, 100vw); height: 100%; background: var(--panel); border-left: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: -20px 0 40px #0006; }
.drawer > header { display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; border-bottom: 1px solid var(--border); }
.drawer h2 { margin: 0; font-size: 17px; }
.close { padding: 4px 10px; }
.drawer-body { flex: 1; overflow-y: auto; padding: 4px 20px 0; }
.manual { display: flex; flex-direction: column; gap: 12px; padding-top: 12px; }
.manual p { font-size: 12px; line-height: 1.7; margin: 0; }
.manual :deep(.panel) { padding: 14px; }
.drawer-enter-active, .drawer-leave-active { transition: opacity .18s; }
.drawer-enter-active .drawer, .drawer-leave-active .drawer { transition: transform .22s cubic-bezier(.2, .8, .2, 1); }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer, .drawer-leave-to .drawer { transform: translateX(40px); }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .layout > :first-child { position: static; max-height: 360px; }
  .brand small { display: none; }
}
</style>
