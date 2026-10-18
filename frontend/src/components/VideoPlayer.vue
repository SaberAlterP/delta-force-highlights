<script setup>
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import videojs from 'video.js'
import 'video.js/dist/video-js.css'
import { useStore } from '../store'
import { api } from '../api'
import { fmtTime } from '../util'

const store = useStore()
const videoEl = ref(null)
const playerRoot = ref(null)
let player = null
const currentTime = ref(0)
const DEFAULT_VOLUME = 0.2

const duration = computed(() => store.video?.duration || 0)
const isFourThree = computed(() => {
  const video = store.video
  return !!(video?.width && video?.height && video.width / video.height < 1.55)
})
const stretchPreview = computed(() => store.stretch169 && isFourThree.value)

onMounted(() => {
  player = videojs(videoEl.value, {
    controls: true,
    preload: 'auto',
    fluid: true,
    aspectRatio: '16:9',
    playbackRates: [0.5, 1, 1.5, 2],
    sources: [{ src: api.videoUrl(store.video.upload_id), type: 'video/mp4' }],
  })
  player.volume(DEFAULT_VOLUME)
  player.on('timeupdate', () => {
    currentTime.value = player.currentTime()
    store.currentTime = currentTime.value
  })
  player.on('loadedmetadata', renderMarkers)
})

onBeforeUnmount(() => { if (player) player.dispose() })

function renderMarkers() {
  if (!player) return
  const seekBar = player.controlBar?.progressControl?.seekBar?.el()
  if (!seekBar) return
  // 清除旧标记
  seekBar.querySelectorAll('.kill-marker').forEach(e => e.remove())
  const dur = player.duration() || duration.value
  if (!dur) return
  store.kills.forEach(k => {
    const m = document.createElement('div')
    m.className = 'kill-marker'
    m.style.left = (k.time / dur * 100) + '%'
    m.title = `击杀 @ ${fmtTime(k.time)}`
    m.addEventListener('click', (e) => {
      e.stopPropagation()
      seek(k.time)
    })
    seekBar.appendChild(m)
  })
}

function seek(t) {
  if (!player) return
  player.currentTime(Math.max(0, t))
  player.play()
}

// 切换当前视频时，换播放源并重画标记
watch(() => store.video?.upload_id, (id, old) => {
  if (id && id !== old && player) {
    player.src({ src: api.videoUrl(id), type: 'video/mp4' })
    player.load()
    player.one('loadedmetadata', () => {
      renderMarkers()
      if (store.seekTo) seek(store.seekTo.t)
    })
  }
})

watch(() => store.seekTo, (v) => { if (v) seek(v.t) })
watch(() => store.kills.length, () => renderMarkers())
watch(() => store.kills.map(k => k.time).join(','), () => renderMarkers())

function addSegmentHere() { store.addSegmentAt(currentTime.value) }

// 区域叠加（百分比）
function boxStyle(region) {
  const [x1, y1, x2, y2] = region
  return {
    left: x1 * 100 + '%',
    top: y1 * 100 + '%',
    width: (x2 - x1) * 100 + '%',
    height: (y2 - y1) * 100 + '%',
  }
}
</script>

<template>
  <div class="panel player-panel">
    <!-- video.js 接管 <video> 后会改它的 class；动态 class 只能放在外层，否则会冲掉 vjs-tech 导致画面掉出播放框 -->
    <div ref="playerRoot" class="player-wrap" :class="{ 'is-stretched': stretchPreview }">
      <video ref="videoEl" class="video-js vjs-big-play-centered"></video>

      <div v-if="store.showRegions" class="region-overlay">
        <div class="rbox id" :style="boxStyle(store.regions.id_region)">
          <span>ID 区</span>
        </div>
        <div class="rbox prompt" :style="boxStyle(store.regions.prompt_region)">
          <span>击倒提示区</span>
        </div>
      </div>
    </div>

    <div class="row controls">
      <span class="time muted">{{ fmtTime(currentTime) }} / {{ fmtTime(duration) }}</span>
      <span v-if="stretchPreview" class="preview-mode">4:3 → 16:9 拉伸预览</span>
      <span class="spacer"></span>
      <button class="primary" @click="addSegmentHere">＋ 在当前位置建片段</button>
    </div>
  </div>
</template>

<style scoped>
.player-panel { padding: 9px 12px 8px; scroll-margin-top: 8px; }
/* 按视口高度定宽：播放器约占 65% 屏高，下方时间轴仍在同一屏内 */
.player-wrap, .controls { width: min(100%, calc(65vh * 16 / 9)); margin-inline: auto; }
.player-wrap { position: relative; box-shadow: 0 10px 28px rgba(0, 0, 0, .28); }
.video-js { width: 100%; border-radius: 8px; overflow: hidden; }
.player-wrap.is-stretched :deep(.vjs-tech) { object-fit: fill !important; }

.region-overlay {
  position: absolute; inset: 0; pointer-events: none;
}
.rbox {
  position: absolute; border: 2px solid; border-radius: 4px;
  display: flex; align-items: flex-start; justify-content: flex-start;
}
.rbox span {
  font-size: 11px; padding: 1px 5px; border-radius: 0 0 4px 0;
  color: #000; font-weight: 600;
}
.rbox.id { border-color: var(--accent); background: rgba(245,166,35,.12); }
.rbox.id span { background: var(--accent); }
.rbox.prompt { border-color: #4aa3ff; background: rgba(74,163,255,.12); }
.rbox.prompt span { background: #4aa3ff; }

.controls { margin-top: 7px; }
.time { font-variant-numeric: tabular-nums; }
.preview-mode {
  padding: 3px 7px; color: var(--accent-2); background: #2a2213;
  border: 1px solid #5d4820; border-radius: 999px; font-size: 10px;
}

</style>

<style>
/* 击杀标记（非 scoped，因为是注入到 video.js DOM 里的） */
.kill-marker {
  position: absolute; top: -2px; bottom: -2px; width: 3px;
  margin-left: -1px;
  background: var(--accent, #f5a623);
  box-shadow: 0 0 4px rgba(245,166,35,.9);
  cursor: pointer; z-index: 2;
}
.kill-marker:hover { width: 5px; background: #ffce5c; }
</style>
