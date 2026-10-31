<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useStore } from './store'
import GameList from './components/GameList.vue'
import GameDetail from './components/GameDetail.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import GuidePanel from './components/GuidePanel.vue'
import UploadPanel from './components/UploadPanel.vue'
import AnalyzePanel from './components/AnalyzePanel.vue'
import MontageStudio from './montage/MontageStudio.vue'

const store = useStore()
let timer
const settings = computed(() => store.workflow?.settings)
const ready = computed(() => settings.value && settings.value.player_id && settings.value.watch_root && settings.value.output_root)
const queued = computed(() => (store.workflow?.records || []).filter(r => ['waiting', 'processing'].includes(r.status)).length)
const titles = { settings: '设置', guide: '使用指南', manual: '手动识别录像' }

// 对局列表收起后把宽度让给剪辑区；记住上次的选择
const LS_SIDEBAR = 'sidebar_collapsed'
const sidebarCollapsed = ref(localStorage.getItem(LS_SIDEBAR) === '1')
watch(sidebarCollapsed, v => localStorage.setItem(LS_SIDEBAR, v ? '1' : '0'))

// 两个平行的部分：自动剪素材（原有）/ 集锦剪辑（音乐卡点）
const LS_MODE = 'df.mode'
// 首页分成两部分：自动剪素材 / 集锦剪辑；打开时先回到首页
const mode = ref('home')
watch(mode, v => { if (v !== 'home') localStorage.setItem(LS_MODE, v) })
const lastMode = localStorage.getItem(LS_MODE) === 'montage' ? 'montage' : 'clips'

function onKey(e) { if (e.key === 'Escape') store.panel = '' }
// 页面在后台标签页时不轮询，切回来立刻刷新一次
function onVisible() { if (!document.hidden) store.refreshWorkflow() }
onMounted(async () => {
  store.loadConfig()
  await store.refreshWorkflow()
  // 第一次打开、还没填设置时直接给出指南
  if (store.workflow && !ready.value && mode.value === 'clips') store.panel = 'guide'
  timer = setInterval(() => { if (!document.hidden) store.refreshWorkflow() }, 4000)
  window.addEventListener('keydown', onKey)
  document.addEventListener('visibilitychange', onVisible)
})
onUnmounted(() => {
  clearInterval(timer)
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('visibilitychange', onVisible)
})
watch(() => store.workflow?.settings.player_id, (id) => { if (id && !store.playerId) store.setPlayerId(id) })
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand" style="cursor:pointer" title="回到首页" @click="mode = 'home'">
        <span class="mark">▲</span>
        <div><b>三角洲 · 多杀集锦</b><small>打完一局，自动剪好高光</small></div>
      </div>
      <div class="modes" role="tablist">
        <button role="tab" :aria-selected="mode === 'home'" :class="{ on: mode === 'home' }" @click="mode = 'home'">首页</button>
        <button role="tab" :aria-selected="mode === 'clips'" :class="{ on: mode === 'clips' }" @click="mode = 'clips'">自动剪素材</button>
        <button role="tab" :aria-selected="mode === 'montage'" :class="{ on: mode === 'montage' }" @click="mode = 'montage'">集锦剪辑</button>
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

    <main v-if="mode === 'home'" class="home">
      <h1>你想做什么？</h1>
      <div class="cards">
        <button class="card" :class="{ last: lastMode === 'clips' }" @click="mode = 'clips'">
          <span class="ico">🎯</span>
          <b>自动剪素材</b>
          <p>打完一局自动在录像里找出「N 秒内 M 杀」的精彩片段，整理成集锦包；也可以手动建片段、调整范围再导出。</p>
          <em>进入 →</em>
        </button>
        <button class="card" :class="{ last: lastMode === 'montage' }" @click="mode = 'montage'">
          <span class="ico">🎬</span>
          <b>集锦剪辑</b>
          <p>把多局高光按一首歌剪成音乐卡点视频：自动分析节拍、击杀对齐重音，配转场、开头结尾，可手动微调。</p>
          <em>进入 →</em>
        </button>
      </div>
    </main>
    <main v-else-if="mode === 'clips'" class="layout" :class="{ narrow: sidebarCollapsed }">
      <GameList v-model:collapsed="sidebarCollapsed" />
      <GameDetail />
    </main>
    <MontageStudio v-else />

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
.modes { display: flex; padding: 3px; gap: 2px; background: var(--bg); border: 1px solid var(--border); border-radius: 9px; }
.modes button { border: 0; padding: 5px 14px; font-size: 13px; background: transparent; color: var(--muted); border-radius: 6px; }
.modes button.on { background: var(--panel-2); color: var(--accent); font-weight: 600; }
nav { display: flex; gap: 6px; } nav button { font-size: 13px; padding: 7px 14px; }
.home { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 28px; padding: 40px 18px; }
.home h1 { margin: 0; font-size: 26px; letter-spacing: 1px; }
.cards { display: grid; grid-template-columns: repeat(2, minmax(0, 340px)); gap: 20px; }
.card { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; text-align: left; padding: 26px; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; transition: transform .15s, border-color .15s; }
.card:hover { transform: translateY(-3px); border-color: var(--accent); }
.card.last { border-color: #f5a62360; }
.card .ico { font-size: 34px; } .card b { font-size: 19px; }
.card p { margin: 0; font-size: 13px; line-height: 1.8; color: var(--muted); }
.card em { margin-top: auto; font-style: normal; color: var(--accent); font-size: 13px; }
@media (max-width: 760px) { .cards { grid-template-columns: 1fr; } }
.offline { margin: 10px 18px 0; padding: 8px 12px; font-size: 12px; color: #f0a6a8; background: #2a1718; border: 1px solid #46282b; border-radius: 6px; }
.layout { flex: 1; display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 14px; padding: 14px 18px; align-items: start; }
.layout.narrow { grid-template-columns: 64px minmax(0, 1fr); }
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
  .layout, .layout.narrow { grid-template-columns: 1fr; }
  .layout > :first-child { position: static; max-height: 360px; }
  .brand small { display: none; }
}
</style>
