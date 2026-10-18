<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useStore } from '../store'
import { fmtTime } from '../util'

const store = useStore()
const scrollerEl = ref(null)
const trackEl = ref(null)
const zoomPower = ref(0)
const focusedKillId = ref(null)
const dragInfo = ref(null)
const visibleStart = ref(0)
const visibleEnd = ref(0)

const duration = computed(() => store.video?.duration || 0)
const kills = computed(() => store.sortedKills)
const zoom = computed(() => 2 ** zoomPower.value)
const canvasStyle = computed(() => ({ width: `${zoom.value * 100}%` }))
const editStep = computed(() => zoom.value >= 16 ? 0.01 : zoom.value >= 4 ? 0.05 : 0.1)
const focusedKill = computed(() => store.kills.find(k => k.id === focusedKillId.value) || null)

function clipRange(k) { return store.clipRange(k) }
function pctLeft(k) { return duration.value ? clipRange(k).start / duration.value * 100 : 0 }
function pctWidth(k) {
  const range = clipRange(k)
  return duration.value ? Math.max(0, range.end - range.start) / duration.value * 100 : 0
}
function killPctInClip(k) {
  const range = clipRange(k)
  const span = range.end - range.start
  return span > 0 ? (k.time - range.start) / span * 100 : 0
}
const playheadPct = computed(() => duration.value ? store.currentTime / duration.value * 100 : 0)

function niceTickStep(raw) {
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
  return steps.find(step => step >= raw) || Math.ceil(raw / 600) * 600
}

const rulerTicks = computed(() => {
  if (!duration.value) return []
  const step = niceTickStep(duration.value / (10 * zoom.value))
  const ticks = []
  for (let time = 0; time <= duration.value + step * 0.01; time += step) {
    ticks.push({ time, left: time / duration.value * 100 })
  }
  return ticks
})

function preciseTime(value) {
  const safe = Math.max(0, Number(value) || 0)
  const minutes = Math.floor(safe / 60)
  const seconds = safe - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(2).padStart(5, '0')}`
}

function timeAtClientX(clientX) {
  const rect = trackEl.value.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  return ratio * duration.value
}

function updateVisibleRange() {
  const scroller = scrollerEl.value
  if (!scroller || !duration.value) return
  visibleStart.value = scroller.scrollLeft / scroller.scrollWidth * duration.value
  visibleEnd.value = Math.min(duration.value, (scroller.scrollLeft + scroller.clientWidth) / scroller.scrollWidth * duration.value)
}

async function setZoomPower(nextPower, clientX = null) {
  const scroller = scrollerEl.value
  if (!scroller || !duration.value) {
    zoomPower.value = Math.max(0, Math.min(6, nextPower))
    return
  }

  const scrollerRect = scroller.getBoundingClientRect()
  const anchorRatio = clientX == null
    ? 0.5
    : Math.min(1, Math.max(0, (clientX - scrollerRect.left) / scrollerRect.width))
  const anchorTime = (scroller.scrollLeft + anchorRatio * scroller.clientWidth) / scroller.scrollWidth * duration.value

  zoomPower.value = Math.max(0, Math.min(6, Number(nextPower)))
  await nextTick()
  scroller.scrollLeft = anchorTime / duration.value * scroller.scrollWidth - anchorRatio * scroller.clientWidth
  updateVisibleRange()
}

function onZoomWheel(event) {
  const direction = event.deltaY < 0 ? 1 : -1
  setZoomPower(zoomPower.value + direction, event.clientX)
}

function centerOn(time) {
  const scroller = scrollerEl.value
  if (!scroller || !duration.value) return
  scroller.scrollTo({
    left: time / duration.value * scroller.scrollWidth - scroller.clientWidth / 2,
    behavior: 'smooth',
  })
}

function startDrag(event, k, edge) {
  event.stopPropagation()
  event.preventDefault()
  focusedKillId.value = k.id
  dragInfo.value = { id: k.id, edge, time: edge === 'start' ? clipRange(k).start : clipRange(k).end }
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', endDrag)
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
}

function quantize(value) {
  const step = editStep.value
  return Math.round(value / step) * step
}

function onDrag(event) {
  if (!dragInfo.value) return
  const time = timeAtClientX(event.clientX)
  const k = store.kills.find(item => item.id === dragInfo.value.id)
  if (!k) return
  const minimum = editStep.value

  if (dragInfo.value.edge === 'start') {
    k.pre = Number(Math.max(minimum, Math.min(k.time, quantize(k.time - time))).toFixed(2))
    dragInfo.value.time = clipRange(k).start
  } else {
    k.post = Number(Math.max(minimum, Math.min(duration.value - k.time, quantize(time - k.time))).toFixed(2))
    dragInfo.value.time = clipRange(k).end
  }
}

function endDrag() {
  if (!dragInfo.value) return
  const id = dragInfo.value.id
  const k = store.kills.find(item => item.id === id)
  dragInfo.value = null
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', endDrag)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  if (k) store.updateKill(id, { pre: k.pre, post: k.post })
}

function selectClip(k) {
  focusedKillId.value = k.id
  store.requestSeek(k.time)
}

function seekToTrack(event) { store.requestSeek(timeAtClientX(event.clientX)) }

function nudgeFocused(direction) {
  const k = focusedKill.value
  if (!k) return
  const nextTime = Math.max(0, Math.min(duration.value, k.time + direction * editStep.value))
  store.updateKill(k.id, { time: Number(nextTime.toFixed(2)) })
  store.requestSeek(nextTime)
}

function onKeydown(event) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const direction = event.key === 'ArrowLeft' ? -1 : 1
  if (event.shiftKey) {
    store.requestSeek(Math.max(0, Math.min(duration.value, store.currentTime + direction * editStep.value)))
  } else {
    nudgeFocused(direction)
  }
}

function updateFocusedEdge(edge, value) {
  const k = focusedKill.value
  if (!k) return
  const numeric = Math.max(0, Math.min(duration.value, Number(value)))
  if (edge === 'start') {
    store.updateKill(k.id, { pre: Number(Math.max(editStep.value, k.time - Math.min(k.time, numeric)).toFixed(2)) })
  } else {
    store.updateKill(k.id, { post: Number(Math.max(editStep.value, Math.min(duration.value, numeric) - k.time).toFixed(2)) })
  }
}

function updateFocusedTime(value) {
  const k = focusedKill.value
  if (!k) return
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return
  const time = Number(Math.max(0, Math.min(duration.value, numeric)).toFixed(2))
  store.updateKill(k.id, { time })
  store.requestSeek(time)
}

watch(duration, async () => { await nextTick(); updateVisibleRange() })
onMounted(() => updateVisibleRange())
onBeforeUnmount(endDrag)
</script>

<template>
  <div v-if="kills.length" class="panel timeline-panel">
    <div class="timeline-head">
      <div>
        <div class="timeline-title">精密剪辑时间轴</div>
        <div class="timeline-sub">拖动两端手柄调整范围 · Ctrl + 滚轮缩放 · 方向键微调击杀点</div>
      </div>
      <div class="zoom-console">
        <button class="zoom-btn" :disabled="zoomPower === 0" aria-label="缩小时间轴" @click="setZoomPower(zoomPower - 1)">−</button>
        <input type="range" min="0" max="6" step="1" :value="zoomPower" aria-label="时间轴缩放"
               @input="setZoomPower(Number($event.target.value))" />
        <button class="zoom-btn" :disabled="zoomPower === 6" aria-label="放大时间轴" @click="setZoomPower(zoomPower + 1)">＋</button>
        <output>{{ zoom }}×</output>
        <button class="locate-btn" title="让播放头回到视野中央" @click="centerOn(store.currentTime)">定位播放头</button>
      </div>
    </div>

    <div class="window-readout">
      <span>视窗 {{ preciseTime(visibleStart) }} — {{ preciseTime(visibleEnd || duration) }}</span>
      <span>拖动精度 <b>{{ editStep.toFixed(2) }}s</b></span>
    </div>

    <div ref="scrollerEl" class="timeline-scroller" tabindex="0" @scroll="updateVisibleRange"
         @wheel.ctrl.prevent="onZoomWheel" @keydown="onKeydown">
      <div ref="trackEl" class="track" :style="canvasStyle" @click="seekToTrack">
        <div class="ruler" aria-hidden="true">
          <span v-for="tick in rulerTicks" :key="tick.time" class="tick" :style="{ left: tick.left + '%' }">
            <i></i><em>{{ fmtTime(tick.time) }}</em>
          </span>
        </div>

        <div
          v-for="(k, index) in kills"
          :key="k.id"
          class="clip"
          :class="{ focused: focusedKillId === k.id }"
          :style="{ left: pctLeft(k) + '%', width: pctWidth(k) + '%' }"
          :title="`#${index + 1}  ${preciseTime(clipRange(k).start)} – ${preciseTime(clipRange(k).end)}`"
          @click.stop="selectClip(k)"
        >
          <span class="handle left" @mousedown="startDrag($event, k, 'start')" @click.stop></span>
          <span class="kill-point" :style="{ left: killPctInClip(k) + '%' }"></span>
          <span class="handle right" @mousedown="startDrag($event, k, 'end')" @click.stop></span>
          <span class="clip-index">#{{ index + 1 }}</span>
        </div>

        <div class="playhead" :style="{ left: playheadPct + '%' }">
          <span>{{ preciseTime(store.currentTime) }}</span>
        </div>

        <div v-if="dragInfo" class="drag-readout" :style="{ left: (dragInfo.time / duration * 100) + '%' }">
          {{ preciseTime(dragInfo.time) }}
        </div>
      </div>
    </div>

    <div v-if="focusedKill" class="precision-strip">
      <span class="selected-chip">#{{ kills.findIndex(k => k.id === focusedKill.id) + 1 }}</span>
      <label>
        入点
        <input type="number" :step="editStep" min="0" :max="focusedKill.time"
               :value="clipRange(focusedKill).start.toFixed(2)" @change="updateFocusedEdge('start', $event.target.value)" />
      </label>
      <label>
        击杀点
        <input type="number" :step="editStep" min="0" :max="duration" :value="focusedKill.time.toFixed(2)"
               @change="updateFocusedTime($event.target.value)" />
      </label>
      <label>
        出点
        <input type="number" :step="editStep" :min="focusedKill.time" :max="duration"
               :value="clipRange(focusedKill).end.toFixed(2)" @change="updateFocusedEdge('end', $event.target.value)" />
      </label>
      <span class="precision-help muted">选中片段后，可用 ← → 按当前精度微调击杀点；Shift + ← → 微移播放头</span>
    </div>
  </div>
</template>

<style scoped>
.timeline-panel { padding: 10px 12px 12px; overflow: hidden; }
.timeline-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 8px; }
.timeline-title { font-size: 14px; font-weight: 700; letter-spacing: .02em; }
.timeline-sub { margin-top: 3px; color: var(--muted); font-size: 10px; }
.zoom-console { display: flex; align-items: center; gap: 6px; padding: 5px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel-2); }
.zoom-console input[type='range'] { width: 98px; padding: 0; accent-color: var(--accent); }
.zoom-console output { width: 32px; color: var(--accent-2); font: 700 11px Consolas, monospace; text-align: center; }
.zoom-btn, .locate-btn { padding: 4px 8px; border-radius: 5px; font-size: 11px; }
.zoom-btn { width: 27px; color: var(--accent); font-size: 16px; line-height: 16px; }
.locate-btn { white-space: nowrap; }
.window-readout { display: flex; justify-content: space-between; margin: 0 2px 6px; color: #788493; font: 10px Consolas, monospace; }
.window-readout b { color: var(--accent); }
.timeline-scroller { overflow-x: auto; overflow-y: hidden; border: 1px solid var(--border); border-radius: 8px; background: #0b0e13; scrollbar-color: #46505e #171c24; scrollbar-width: thin; }
.timeline-scroller:focus { outline: 1px solid var(--accent); outline-offset: 2px; }
.timeline-scroller::-webkit-scrollbar { height: 10px; }
.timeline-scroller::-webkit-scrollbar-track { background: #151a21; }
.timeline-scroller::-webkit-scrollbar-thumb { background: #46505e; border: 2px solid #151a21; border-radius: 10px; }
.track { position: relative; height: 72px; min-width: 100%; cursor: crosshair; background: repeating-linear-gradient(90deg, rgba(255,255,255,.018) 0 1px, transparent 1px 12px); }
.ruler { position: absolute; inset: 0 0 auto; height: 24px; border-bottom: 1px solid #28303b; pointer-events: none; }
.tick { position: absolute; top: 0; height: 100%; }
.tick i { display: block; width: 1px; height: 7px; background: #596575; }
.tick em { position: absolute; top: 8px; left: 4px; color: #707c8c; font: normal 9px Consolas, monospace; white-space: nowrap; }
.clip { position: absolute; top: 31px; height: 30px; min-width: 6px; border: 1px solid #b97916; border-radius: 4px; background: linear-gradient(180deg, rgba(245,166,35,.28), rgba(245,166,35,.14)); cursor: pointer; box-shadow: inset 0 1px rgba(255,255,255,.08); }
.clip:hover, .clip.focused { border-color: var(--accent-2); background: linear-gradient(180deg, rgba(245,166,35,.43), rgba(245,166,35,.2)); }
.clip.focused { box-shadow: 0 0 0 1px rgba(245,166,35,.35), 0 0 14px rgba(245,166,35,.14); }
.handle { position: absolute; z-index: 4; top: -3px; bottom: -3px; width: 10px; background: var(--accent); cursor: ew-resize; }
.handle::after { content: ''; position: absolute; top: 9px; bottom: 9px; left: 4px; border-left: 1px solid rgba(30,20,3,.6); }
.handle.left { left: -2px; border-radius: 4px 1px 1px 4px; }
.handle.right { right: -2px; border-radius: 1px 4px 4px 1px; }
.handle:hover { background: var(--accent-2); }
.kill-point { position: absolute; z-index: 3; top: -9px; bottom: -9px; width: 2px; margin-left: -1px; background: #f4f7fb; box-shadow: 0 0 5px rgba(255,255,255,.85); }
.clip-index { position: absolute; left: 12px; top: 8px; color: #ffe0a3; font: 700 10px Consolas, monospace; pointer-events: none; }
.playhead { position: absolute; z-index: 6; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #4aa3ff; pointer-events: none; box-shadow: 0 0 7px rgba(74,163,255,.9); }
.playhead::before { content: ''; position: absolute; top: 0; left: -4px; border: 5px solid transparent; border-top-color: #4aa3ff; }
.playhead span { position: absolute; top: 3px; left: 7px; padding: 2px 4px; color: #9acbff; background: #101a25; font: 9px Consolas, monospace; white-space: nowrap; }
.drag-readout { position: absolute; z-index: 8; top: 25px; transform: translateX(-50%); padding: 3px 6px; color: #171007; background: var(--accent-2); border-radius: 4px; font: 700 10px Consolas, monospace; pointer-events: none; }
.precision-strip { display: flex; align-items: center; gap: 10px; margin-top: 10px; padding: 8px 9px; border: 1px solid #343e4a; border-radius: 8px; background: #141a22; }
.selected-chip { display: grid; place-items: center; width: 30px; height: 27px; color: #211706; background: var(--accent); border-radius: 5px; font: 800 11px Consolas, monospace; }
.precision-strip label { display: flex; align-items: center; gap: 5px; color: #9ca7b4; font-size: 10px; white-space: nowrap; }
.precision-strip input { width: 82px; padding: 4px 6px; font: 11px Consolas, monospace; }
.precision-help { margin-left: auto; font-size: 9px; line-height: 1.35; }

@media (max-width: 900px) {
  .timeline-head { align-items: stretch; flex-direction: column; }
  .zoom-console { align-self: flex-start; }
  .precision-strip { align-items: flex-start; flex-wrap: wrap; }
  .precision-help { width: 100%; margin-left: 40px; }
}
</style>
