<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useStore } from '../store'
import { fmtTime } from '../util'

const store = useStore()
const scrollerEl = ref(null)
const trackEl = ref(null)
const zoomPower = ref(0)
const focusedId = ref(null)
const dragInfo = ref(null)

const duration = computed(() => store.video?.duration || 0)
const kills = computed(() => store.sortedKills)
const segments = computed(() => [...store.segments].sort((a, b) => a.start - b.start))
const zoom = computed(() => 2 ** zoomPower.value)
const canvasStyle = computed(() => ({ width: `${zoom.value * 100}%` }))
const editStep = computed(() => zoom.value >= 16 ? 0.01 : zoom.value >= 4 ? 0.05 : 0.1)
const focused = computed(() => store.segments.find(s => s.id === focusedId.value) || null)
const focusedIndex = computed(() => segments.value.findIndex(s => s.id === focusedId.value))
const pct = (t) => duration.value ? t / duration.value * 100 : 0
const playheadPct = computed(() => pct(store.currentTime))

function markerKind(k) {
  if (k.event_type === 'loot') return 'loot'
  if (['vehicle', 'other'].includes(k.event_type)) return 'other'
  return 'kill'
}
function markerTitle(k) {
  const name = k.label || ({ loot: '摸金', other: '其他事件' })[markerKind(k)] || '击杀'
  return `${name} @ ${preciseTime(k.time)}`
}

function niceTickStep(raw) {
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
  return steps.find(step => step >= raw) || Math.ceil(raw / 600) * 600
}
const rulerTicks = computed(() => {
  if (!duration.value) return []
  const step = niceTickStep(duration.value / (10 * zoom.value))
  const ticks = []
  for (let time = 0; time <= duration.value + step * 0.01; time += step) ticks.push({ time, left: pct(time) })
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
  return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) * duration.value
}
async function setZoomPower(nextPower, clientX = null) {
  const scroller = scrollerEl.value
  if (!scroller || !duration.value) { zoomPower.value = Math.max(0, Math.min(6, nextPower)); return }
  const rect = scroller.getBoundingClientRect()
  const anchorRatio = clientX == null ? 0.5 : Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  const anchorTime = (scroller.scrollLeft + anchorRatio * scroller.clientWidth) / scroller.scrollWidth * duration.value
  zoomPower.value = Math.max(0, Math.min(6, Number(nextPower)))
  await nextTick()
  scroller.scrollLeft = anchorTime / duration.value * scroller.scrollWidth - anchorRatio * scroller.clientWidth
}
function onZoomWheel(event) { setZoomPower(zoomPower.value + (event.deltaY < 0 ? 1 : -1), event.clientX) }
function centerOn(time) {
  const scroller = scrollerEl.value
  if (!scroller || !duration.value) return
  scroller.scrollTo({ left: time / duration.value * scroller.scrollWidth - scroller.clientWidth / 2, behavior: 'smooth' })
}
const quantize = (value) => Math.round(value / editStep.value) * editStep.value

// 拖动片段：edge = start（入点）| end（出点）| move（整体平移）
function startDrag(event, seg, edge) {
  event.stopPropagation(); event.preventDefault()
  focusedId.value = seg.id
  dragInfo.value = { id: seg.id, edge, origin: timeAtClientX(event.clientX), start: seg.start, end: seg.end,
    time: edge === 'end' ? seg.end : seg.start, moved: false }
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', endDrag)
  document.body.style.cursor = edge === 'move' ? 'grabbing' : 'ew-resize'
  document.body.style.userSelect = 'none'
}
function onDrag(event) {
  const info = dragInfo.value
  const seg = info && store.segments.find(s => s.id === info.id)
  if (!seg) return
  const t = timeAtClientX(event.clientX), min = editStep.value
  info.moved = true
  if (info.edge === 'start') seg.start = +Math.max(0, Math.min(seg.end - min, quantize(t))).toFixed(2)
  else if (info.edge === 'end') seg.end = +Math.min(duration.value, Math.max(seg.start + min, quantize(t))).toFixed(2)
  else {
    const span = info.end - info.start
    const start = Math.max(0, Math.min(duration.value - span, quantize(info.start + t - info.origin)))
    seg.start = +start.toFixed(2); seg.end = +(start + span).toFixed(2)
  }
  info.time = info.edge === 'end' ? seg.end : seg.start
}
function endDrag() {
  const info = dragInfo.value
  if (!info) return
  dragInfo.value = null
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', endDrag)
  document.body.style.cursor = ''; document.body.style.userSelect = ''
  const seg = store.segments.find(s => s.id === info.id)
  if (!seg) return
  if (info.moved) store.updateSegment(seg.id, { start: seg.start, end: seg.end })
  store.requestSeek(info.edge === 'end' ? seg.end : seg.start)
}

function seekToTrack(event) { store.requestSeek(timeAtClientX(event.clientX)) }
function addHere() { focusedId.value = store.addSegmentAt(store.currentTime).id }
function removeFocused() {
  if (!focused.value) return
  store.removeSegment(focused.value.id); focusedId.value = null
}
function setEdge(edge, value) {
  const seg = focused.value, n = Number(value)
  if (!seg || !Number.isFinite(n)) return
  const t = +Math.max(0, Math.min(duration.value, n)).toFixed(2)
  if (edge === 'start' && t < seg.end) store.updateSegment(seg.id, { start: t })
  if (edge === 'end' && t > seg.start) store.updateSegment(seg.id, { end: t })
}

function onKeydown(event) {
  if (event.target.tagName === 'INPUT') return
  const key = event.key.toLowerCase()
  if (key === 'arrowleft' || key === 'arrowright') {
    event.preventDefault()
    const step = editStep.value * (event.shiftKey ? 10 : 1) * (key === 'arrowleft' ? -1 : 1)
    store.requestSeek(Math.max(0, Math.min(duration.value, store.currentTime + step)))
  } else if (key === 'i') setEdge('start', store.currentTime)
  else if (key === 'o') setEdge('end', store.currentTime)
  else if (key === 'delete') removeFocused()
  else if (key === 'n') addHere()
}

watch(() => store.video?.upload_id, () => { focusedId.value = null })
onBeforeUnmount(endDrag)
</script>

<template>
  <div v-if="store.video" class="panel timeline-panel">
    <div class="timeline-head">
      <div class="head-actions">
        <button class="primary small" title="快捷键 N" @click="addHere">＋ 在当前位置建片段</button>
        <button class="danger small" :disabled="!focused" title="快捷键 Delete" @click="removeFocused">删除选中片段</button>
        <span class="legend"><i class="kill"></i>击杀<i class="loot"></i>摸金<i class="seg"></i>片段 {{ segments.length }}</span>
      </div>
      <div class="zoom-console">
        <button class="zoom-btn" :disabled="zoomPower === 0" aria-label="缩小时间轴" @click="setZoomPower(zoomPower - 1)">−</button>
        <input type="range" min="0" max="6" step="1" :value="zoomPower" aria-label="时间轴缩放" @input="setZoomPower(Number($event.target.value))" />
        <button class="zoom-btn" :disabled="zoomPower === 6" aria-label="放大时间轴" @click="setZoomPower(zoomPower + 1)">＋</button>
        <output>{{ zoom }}×</output>
        <button class="locate-btn" title="让播放头回到视野中央" @click="centerOn(store.currentTime)">定位播放头</button>
      </div>
    </div>

    <div ref="scrollerEl" class="timeline-scroller" tabindex="0" @wheel.ctrl.prevent="onZoomWheel" @keydown="onKeydown">
      <div ref="trackEl" class="track" :style="canvasStyle" @click="seekToTrack">
        <div class="ruler" aria-hidden="true">
          <span v-for="tick in rulerTicks" :key="tick.time" class="tick" :style="{ left: tick.left + '%' }"><i></i><em>{{ fmtTime(tick.time) }}</em></span>
        </div>
        <div class="lane-line markers-lane"></div>
        <div class="lane-line segments-lane"></div>

        <button v-for="k in kills" :key="k.id" class="marker" :class="markerKind(k)" :style="{ left: pct(k.time) + '%' }"
                :title="markerTitle(k)" :aria-label="markerTitle(k)" @click.stop="store.requestSeek(k.time)"></button>

        <div v-for="(seg, index) in segments" :key="seg.id" class="clip" :class="{ focused: focusedId === seg.id }"
             :style="{ left: pct(seg.start) + '%', width: pct(seg.end - seg.start) + '%' }"
             :title="`片段 ${index + 1}  ${preciseTime(seg.start)} – ${preciseTime(seg.end)}`"
             @mousedown="startDrag($event, seg, 'move')" @click.stop>
          <span class="handle left" @mousedown="startDrag($event, seg, 'start')"></span>
          <span class="clip-index">{{ seg.label || index + 1 }}</span>
          <span class="handle right" @mousedown="startDrag($event, seg, 'end')"></span>
        </div>

        <div class="playhead" :style="{ left: playheadPct + '%' }"><span>{{ preciseTime(store.currentTime) }}</span></div>
        <div v-if="dragInfo" class="drag-readout" :style="{ left: pct(dragInfo.time) + '%' }">{{ preciseTime(dragInfo.time) }}</div>
      </div>
    </div>

    <div v-if="focused" class="precision-strip">
      <span class="selected-chip">{{ focusedIndex + 1 }}</span>
      <label>入点 <input type="number" :step="editStep" min="0" :value="focused.start.toFixed(2)" @change="setEdge('start', $event.target.value)" /></label>
      <button class="ghost tiny" title="快捷键 I" @click="setEdge('start', store.currentTime)">设到播放头</button>
      <label>出点 <input type="number" :step="editStep" :value="focused.end.toFixed(2)" @change="setEdge('end', $event.target.value)" /></label>
      <button class="ghost tiny" title="快捷键 O" @click="setEdge('end', store.currentTime)">设到播放头</button>
      <span class="muted len">{{ (focused.end - focused.start).toFixed(1) }} 秒</span>
      <input class="seg-label" :value="focused.label" placeholder="片段名（可选）" @change="store.updateSegment(focused.id, { label: $event.target.value })" />
      <button v-if="store.segmentInBasket(focused.id)" class="ghost tiny" disabled>✓ 已在导出列表</button>
      <button v-else class="ghost tiny" @click="store.addSegmentToBasket(focused)">加入导出列表</button>
    </div>
    <p v-else class="tips muted">
      <template v-if="!segments.length">还没有片段。把播放头移到想剪的位置，点「在当前位置建片段」。</template>
      <template v-else>点片段选中它，拖两端调整范围、拖中间整体移动。</template>
      快捷键（先点一下时间轴）：N 建片段 · I / O 把入点 / 出点设到播放头 · ← → 微移播放头 · Delete 删除片段 · Ctrl + 滚轮缩放
    </p>
  </div>
</template>

<style scoped>
.timeline-panel { padding: 10px 12px 12px; overflow: hidden; }
.timeline-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 8px; flex-wrap: wrap; }
.head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.small { padding: 6px 12px; font-size: 12px; }
.tiny { padding: 4px 8px; font-size: 11px; }
.legend { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted); margin-left: 6px; }
.legend i { display: inline-block; width: 9px; height: 9px; margin-left: 8px; border-radius: 2px; }
.legend i.kill { background: #ff6b5e; transform: rotate(45deg); }
.legend i.loot { background: #4aa3ff; transform: rotate(45deg); }
.legend i.seg { background: rgba(245,166,35,.5); border: 1px solid var(--accent); }
.zoom-console { display: flex; align-items: center; gap: 6px; padding: 5px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel-2); }
.zoom-console input[type='range'] { width: 98px; padding: 0; accent-color: var(--accent); }
.zoom-console output { width: 32px; color: var(--accent-2); font: 700 11px Consolas, monospace; text-align: center; }
.zoom-btn, .locate-btn { padding: 4px 8px; border-radius: 5px; font-size: 11px; }
.zoom-btn { width: 27px; color: var(--accent); font-size: 16px; line-height: 16px; }
.locate-btn { white-space: nowrap; }
.timeline-scroller { overflow-x: auto; overflow-y: hidden; border: 1px solid var(--border); border-radius: 8px; background: #0b0e13; scrollbar-color: #46505e #171c24; scrollbar-width: thin; }
.timeline-scroller:focus { outline: 1px solid var(--accent); outline-offset: 2px; }
.track { position: relative; height: 96px; min-width: 100%; cursor: crosshair; background: repeating-linear-gradient(90deg, rgba(255,255,255,.018) 0 1px, transparent 1px 12px); }
.ruler { position: absolute; inset: 0 0 auto; height: 24px; border-bottom: 1px solid #28303b; pointer-events: none; }
.tick { position: absolute; top: 0; height: 100%; }
.tick i { display: block; width: 1px; height: 7px; background: #596575; }
.tick em { position: absolute; top: 8px; left: 4px; color: #707c8c; font: normal 9px Consolas, monospace; white-space: nowrap; }
.lane-line { position: absolute; left: 0; right: 0; height: 1px; background: #1c232c; pointer-events: none; }
.markers-lane { top: 37px; } .segments-lane { top: 54px; }
.marker { position: absolute; z-index: 5; top: 31px; width: 11px; height: 11px; margin-left: -5.5px; padding: 0; border: 1px solid #0b0e13; border-radius: 2px; transform: rotate(45deg); background: #ff6b5e; cursor: pointer; }
.marker.loot { background: #4aa3ff; } .marker.other { background: #8b95a3; }
.marker:hover:not(:disabled) { transform: rotate(45deg) scale(1.35); border-color: #fff; }
.clip { position: absolute; top: 58px; height: 30px; min-width: 6px; border: 1px solid #b97916; border-radius: 4px; background: linear-gradient(180deg, rgba(245,166,35,.28), rgba(245,166,35,.14)); cursor: grab; box-shadow: inset 0 1px rgba(255,255,255,.08); }
.clip:hover, .clip.focused { border-color: var(--accent-2); background: linear-gradient(180deg, rgba(245,166,35,.43), rgba(245,166,35,.2)); }
.clip.focused { box-shadow: 0 0 0 1px rgba(245,166,35,.35), 0 0 14px rgba(245,166,35,.14); z-index: 3; }
.handle { position: absolute; z-index: 4; top: -3px; bottom: -3px; width: 10px; background: var(--accent); cursor: ew-resize; }
.handle::after { content: ''; position: absolute; top: 9px; bottom: 9px; left: 4px; border-left: 1px solid rgba(30,20,3,.6); }
.handle.left { left: -2px; border-radius: 4px 1px 1px 4px; }
.handle.right { right: -2px; border-radius: 1px 4px 4px 1px; }
.handle:hover { background: var(--accent-2); }
.clip-index { position: absolute; left: 12px; right: 12px; top: 8px; color: #ffe0a3; font: 700 10px Consolas, monospace; pointer-events: none; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.playhead { position: absolute; z-index: 6; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #4aa3ff; pointer-events: none; box-shadow: 0 0 7px rgba(74,163,255,.9); }
.playhead::before { content: ''; position: absolute; top: 0; left: -4px; border: 5px solid transparent; border-top-color: #4aa3ff; }
.playhead span { position: absolute; top: 3px; left: 7px; padding: 2px 4px; color: #9acbff; background: #101a25; font: 9px Consolas, monospace; white-space: nowrap; }
.drag-readout { position: absolute; z-index: 8; top: 25px; transform: translateX(-50%); padding: 3px 6px; color: #171007; background: var(--accent-2); border-radius: 4px; font: 700 10px Consolas, monospace; pointer-events: none; }
.precision-strip { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding: 8px 9px; border: 1px solid #343e4a; border-radius: 8px; background: #141a22; flex-wrap: wrap; }
.selected-chip { display: grid; place-items: center; min-width: 30px; height: 27px; color: #211706; background: var(--accent); border-radius: 5px; font: 800 11px Consolas, monospace; }
.precision-strip label { display: flex; align-items: center; gap: 5px; color: #9ca7b4; font-size: 11px; white-space: nowrap; }
.precision-strip input[type='number'] { width: 82px; padding: 4px 6px; font: 11px Consolas, monospace; }
.len { font-size: 11px; white-space: nowrap; }
.seg-label { flex: 1; min-width: 120px; padding: 4px 8px; font-size: 12px; }
.tips { margin: 8px 2px 0; font-size: 11px; line-height: 1.7; }
</style>
