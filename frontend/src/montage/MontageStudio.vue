<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMontage } from './store'
import MediaBin from './MediaBin.vue'
import MontagePreview from './MontagePreview.vue'
import ClipPreview from './ClipPreview.vue'
import BeatTimeline from './BeatTimeline.vue'
import StylePanel from './StylePanel.vue'
import AgentPanel from './AgentPanel.vue'

const m = useMontage()
const LS_TAB = 'df.montage.tab'
const tab = ref(localStorage.getItem(LS_TAB) || 'style')
watch(tab, v => localStorage.setItem(LS_TAB, v))

let noticeTimer
watch(() => m.notice, v => { clearTimeout(noticeTimer); if (v) noticeTimer = setTimeout(() => { m.notice = '' }, 6000) })
onMounted(() => { if (!m.project) m.init() })
onBeforeUnmount(() => { m.flush(); m.playing = false })
</script>

<template>
  <div class="studio">
    <MediaBin class="bin" />
    <section class="panel stage">
      <ClipPreview v-if="m.source" :key="m.source" />
      <MontagePreview v-show="!m.source" />
    </section>
    <aside class="panel side">
      <nav class="tabs">
        <button :class="{ on: tab === 'style' }" @click="tab = 'style'">剪辑设置</button>
        <button :class="{ on: tab === 'agent' }" @click="tab = 'agent'">助手</button>
      </nav>
      <div class="side-body scroll">
        <StylePanel v-if="tab === 'style'" />
        <AgentPanel v-else />
      </div>
    </aside>
    <BeatTimeline class="tl" />
    <div class="toasts">
      <p v-if="m.error" class="toast err" role="alert" @click="m.error = ''">{{ m.error }} <i>✕</i></p>
      <p v-else-if="m.notice" class="toast" @click="m.notice = ''">{{ m.notice }}</p>
    </div>
  </div>
</template>

<style scoped>
.studio { flex: 1; display: grid; gap: 12px; padding: 12px 18px; grid-template-columns: 290px minmax(0, 1fr) 330px;
  grid-template-rows: minmax(0, auto) auto; grid-template-areas: 'bin stage side' 'tl tl tl'; align-items: start; }
.bin { grid-area: bin; height: calc(62vh); }
.stage { grid-area: stage; padding: 10px; }
.stage :deep(.screen) { max-height: calc(62vh - 62px); aspect-ratio: 16 / 9; margin-inline: auto; width: min(100%, calc((62vh - 62px) * 16 / 9)); }
.side { grid-area: side; height: 62vh; display: flex; flex-direction: column; padding: 0; overflow: hidden; }
.tl { grid-area: tl; }
.tabs { display: flex; border-bottom: 1px solid var(--border); }
.tabs button { flex: 1; border: 0; border-radius: 0; background: transparent; padding: 9px; font-size: 13px; color: var(--muted); }
.tabs button.on { color: var(--accent); box-shadow: inset 0 -2px var(--accent); }
.side-body { flex: 1; min-height: 0; padding: 4px 12px 10px; display: flex; flex-direction: column; }
.toasts { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 40; }
.toast { margin: 0; padding: 9px 14px; font-size: 12px; background: #16301f; border: 1px solid #2b5a3a; color: #b6f0c6; border-radius: 8px; box-shadow: 0 8px 24px #0008; cursor: pointer; max-width: 70vw; }
.toast.err { background: #2a1718; border-color: #46282b; color: #f0a6a8; }
.toast i { font-style: normal; margin-left: 8px; opacity: .7; }
@media (max-width: 1200px) {
  .studio { grid-template-columns: 260px minmax(0, 1fr); grid-template-areas: 'bin stage' 'side side' 'tl tl'; }
  .side { height: auto; max-height: 70vh; }
}
</style>
