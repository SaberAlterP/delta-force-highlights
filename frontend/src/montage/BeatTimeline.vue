<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMontage } from './store'
import { mapi } from './api'

const m = useMontage()
const scroller = ref(null)
const canvas = ref(null)
const width = ref(800)
const zoomPower = ref(0)
const drag = ref(null)          // { kind: 'kill'|'end', shot, kill, t }
let ro = null

const length = computed(() => {
  const plan = m.config?.plan?.duration || 60
  const songLen = m.song?.duration || 0
  return Math.max(m.duration, Math.min(songLen || plan, Math.max(m.duration, plan) + 8), 10)
})
const pps = computed(() => (width.value - 2) / length.value * 2 ** zoomPower.value)
const x = (t) => t * pps.value
const canvasWidth = computed(() => Math.ceil(length.value * pps.value))
const beats = computed(() => (m.song?.beats || []).filter(b => b <= length.value))
const downs = computed(() => new Set(m.song?.downbeats || []))
const accents = computed(() => (m.song?.top || []).slice(0, 12).map((a, i) => ({ ...a, rank: i + 1 })).filter(a => a.t <= length.value))
const transLabel = computed(() => Object.fromEntries((m.presets?.transitions || []).map(t => [t.id, t.label])))
const ticks = computed(() => {
  const step = [1, 2, 5, 10, 15, 30].find(s => s * pps.value >= 60) || 60
  const out = []
  for (let t = 0; t <= length.value; t += step) out.push(t)
  return out
})
const sel = computed(() => m.shots[m.selectedShot] || null)
const sortedKills = (s) => [...s.kills].sort((a, b) => a.at - b.at)
const base = (p) => p.split(/[\\/]/).pop()
const plannedFiles = computed(() => Object.keys(m.project?.clip_kills || {}))

function drawWave() {
  const c = canvas.value, peaks = m.song?.peaks
  if (!c) return
  const w = Math.min(canvasWidth.value, 32000), h = 44
  c.width = w; c.height = h
  const g = c.getContext('2d')
  g.clearRect(0, 0, w, h)
  if (!peaks?.length) return
  const per = m.song.peaks_per_second
  g.fillStyle = '#3d6f9e'
  for (let px = 0; px < w; px++) {
    const t0 = px / pps.value, t1 = (px + 1) / pps.value
    let v = 0
    for (let i = Math.floor(t0 * per); i <= Math.floor(t1 * per) && i < peaks.length; i++) v = Math.max(v, peaks[i])
    const bh = Math.max(1, v * (h - 4))
    g.fillRect(px, (h - bh) / 2, 1, bh)
  }
}
watch([() => m.song, pps], () => nextTick(drawWave))

function timeAt(e) {
  const r = scroller.value.getBoundingClientRect()
  return Math.max(0, (e.clientX - r.left + scroller.value.scrollLeft) / pps.value)
}
function seek(e) { if (!drag.value) { m.playing = false; m.T = Math.min(m.duration || length.value, timeAt(e)) } }

function startDrag(e, kind, shot, kill = null) {
  e.preventDefault(); e.stopPropagation()
  m.selectedShot = shot
  const s = m.shots[shot]
  drag.value = { kind, shot, kill, t: kind === 'end' ? s.end : sortedKills(s)[kill].at, moved: false }
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', endDrag)
  document.body.style.userSelect = 'none'
}
function snapped(e, t) { return e.altKey ? +t.toFixed(3) : m.nearestBeat(t) }
function onDrag(e) {
  if (!drag.value) return
  drag.value.moved = true
  drag.value.t = snapped(e, timeAt(e))
}
async function endDrag() {
  const d = drag.value
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', endDrag)
  document.body.style.userSelect = ''
  drag.value = null
  if (!d?.moved) { if (d?.kind === 'kill') m.T = sortedKills(m.shots[d.shot])[d.kill].at; return }
  if (d.kind === 'kill') await m.ops([{ op: 'move_kill', shot: d.shot, kill: d.kill, at: d.t }])
  else await m.ops([{ op: 'set_end', shot: d.shot, end: d.t }])
}

function setZoom(p, anchorT = null) {
  const sc = scroller.value
  const t = anchorT ?? (sc.scrollLeft + sc.clientWidth / 2) / pps.value
  zoomPower.value = Math.max(0, Math.min(5, p))
  nextTick(() => { sc.scrollLeft = t * pps.value - sc.clientWidth / 2 })
}
function onWheel(e) { if (e.ctrlKey) { e.preventDefault(); setZoom(zoomPower.value + (e.deltaY < 0 ? 1 : -1), timeAt(e)) } }

// 播放时让播放头保持在视野里
watch(() => m.T, (T) => {
  const sc = scroller.value
  if (!sc || drag.value) return
  const px = x(T)
  if (px < sc.scrollLeft + 20 || px > sc.scrollLeft + sc.clientWidth - 40) sc.scrollLeft = px - sc.clientWidth * 0.3
})

function onKey(e) {
  if (m.source || e.ctrlKey || e.metaKey || e.altKey || e.target?.closest?.('input, textarea, select')) return
  if (e.key === 'Delete' && sel.value) { e.preventDefault(); removeShot() }
}
function removeShot() {
  if (!sel.value || !confirm(`从时间线删掉第 ${m.selectedShot + 1} 个镜头？`)) return
  m.ops([{ op: 'delete_shot', shot: m.selectedShot }]); m.selectedShot = null
}
function moveShot(dir) {
  const to = m.selectedShot + dir
  if (to < 0 || to >= m.shots.length) return
  m.ops([{ op: 'move_shot', shot: m.selectedShot, to }]); m.selectedShot = to
}

onMounted(() => {
  ro = new ResizeObserver(([en]) => { width.value = en.contentRect.width })
  ro.observe(scroller.value)
  window.addEventListener('keydown', onKey)
  drawWave()
})
onBeforeUnmount(() => { ro?.disconnect(); window.removeEventListener('keydown', onKey); endDrag() })
</script>

<template>
  <div class="panel bt">
    <div class="head">
      <b>时间线</b>
      <span class="legend muted"><i class="acc"></i>重音（数字越小越重）<i class="kill"></i>击杀落点<i class="down"></i>小节线</span>
      <span class="spacer"></span>
      <span class="muted tip">拖击杀 / 镜头尾巴会吸附到拍点，按住 Alt 不吸附 · Ctrl + 滚轮缩放</span>
      <div class="zoom">
        <button :disabled="zoomPower === 0" @click="setZoom(zoomPower - 1)">−</button>
        <output>{{ 2 ** zoomPower }}×</output>
        <button :disabled="zoomPower === 5" @click="setZoom(zoomPower + 1)">＋</button>
      </div>
    </div>

    <div ref="scroller" class="scroller" @wheel="onWheel">
      <div class="track" :style="{ width: canvasWidth + 'px' }" @mousedown="seek">
        <div class="ruler">
          <span v-for="t in ticks" :key="t" :style="{ left: x(t) + 'px' }">{{ t }}s</span>
        </div>
        <div class="wave"><canvas ref="canvas"></canvas></div>
        <div class="beats">
          <i v-for="b in beats" :key="b" :class="{ down: downs.has(b) }" :style="{ left: x(b) + 'px' }"></i>
          <em v-for="a in accents" :key="a.t" :style="{ left: x(a.t) + 'px' }" :title="`重音 #${a.rank} @ ${a.t}s`">{{ a.rank }}</em>
        </div>
        <div class="shots">
          <div v-for="(s, i) in m.shots" :key="i + s.file" class="shot" :class="{ sel: m.selectedShot === i }"
               :style="{ left: x(s.start) + 'px', width: Math.max(4, x(s.end - s.start)) + 'px',
                         backgroundImage: `linear-gradient(#0b0e13aa, #0b0e13cc), url(${mapi.thumbUrl(s.file, sortedKills(s)[0].src)})` }"
               :title="base(s.file)" @mousedown.stop="m.selectedShot = i; seek($event)">
            <span class="tr" v-if="i > 0 && s.transition_in !== 'cut'">{{ transLabel[s.transition_in] || s.transition_in }}</span>
            <span class="name">{{ i + 1 }} · {{ base(s.file) }}</span>
            <span class="end" title="拖动改镜头结尾" @mousedown="startDrag($event, 'end', i)"></span>
          </div>
          <button v-for="k in m.shots.flatMap((s, i) => sortedKills(s).map((kk, j) => ({ ...kk, shot: i, j })))" :key="`${k.shot}-${k.j}`"
                  class="kill" :style="{ left: x(k.at) + 'px' }" :title="`镜头 ${k.shot + 1} 击杀 ${k.j + 1} @ ${k.at.toFixed(2)}s（拖动换拍点）`"
                  @mousedown="startDrag($event, 'kill', k.shot, k.j)"></button>
        </div>
        <div v-if="drag" class="drag-line" :style="{ left: x(drag.t) + 'px' }"><span>{{ drag.t.toFixed(2) }}s</span></div>
        <div class="playhead" :style="{ left: x(m.T) + 'px' }"></div>
      </div>
    </div>

    <ul v-if="m.project?.errors?.length" class="errors">
      <li v-for="e in m.project.errors" :key="e">⚠ {{ e }}</li>
    </ul>

    <div v-if="sel" class="inspector">
      <span class="chip">镜头 {{ m.selectedShot + 1 }}</span>
      <span class="file" :title="sel.file">{{ base(sel.file) }}</span>
      <span class="muted">{{ sel.start.toFixed(2) }} – {{ sel.end.toFixed(2) }}s</span>
      <label>入场
        <select :value="sel.transition_in || 'cut'" :disabled="m.selectedShot === 0"
                @change="m.ops([{ op: 'set_transition', shot: m.selectedShot, transition: $event.target.value }])">
          <option v-for="t in m.presets?.transitions" :key="t.id" :value="t.id">{{ t.label }}</option>
        </select>
      </label>
      <label v-if="plannedFiles.length > 1">换素材
        <select :value="sel.file" @change="m.ops([{ op: 'replace_clip', shot: m.selectedShot, file: $event.target.value }])">
          <option v-for="f in plannedFiles" :key="f" :value="f">{{ base(f) }}</option>
        </select>
      </label>
      <span class="kills">
        击杀
        <button v-for="(k, j) in sortedKills(sel)" :key="j" class="ghost tiny" :title="`在 ${k.at.toFixed(2)}s，点击删除这个击杀`"
                :disabled="sel.kills.length < 2" @click="m.ops([{ op: 'delete_kill', shot: m.selectedShot, kill: j }])">{{ k.at.toFixed(2) }}s ✕</button>
      </span>
      <span class="spacer"></span>
      <button class="ghost tiny" :disabled="m.selectedShot === 0" @click="moveShot(-1)">← 前移</button>
      <button class="ghost tiny" :disabled="m.selectedShot === m.shots.length - 1" @click="moveShot(1)">后移 →</button>
      <button class="danger tiny" @click="removeShot">删除镜头</button>
    </div>
    <p v-else class="muted foot">点镜头选中它，可以换转场、换素材、调顺序。空格播放，← → 按拍移动播放头。</p>
  </div>
</template>

<style scoped>
.bt { padding: 10px 12px; }
.head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.legend { display: flex; align-items: center; gap: 4px; font-size: 11px; }
.legend i { display: inline-block; width: 9px; height: 9px; margin-left: 8px; border-radius: 2px; }
.legend .acc { background: var(--accent); border-radius: 50%; }
.legend .kill { background: #ff6b5e; transform: rotate(45deg); }
.legend .down { width: 2px; height: 12px; background: #7d8b9c; }
.tip { font-size: 11px; }
.zoom { display: flex; align-items: center; gap: 4px; }
.zoom button { padding: 2px 9px; } .zoom output { width: 30px; text-align: center; font: 11px Consolas, monospace; color: var(--accent-2); }
.scroller { overflow-x: auto; overflow-y: hidden; border: 1px solid var(--border); border-radius: 8px; background: #0b0e13; }
.track { position: relative; height: 172px; min-width: 100%; cursor: crosshair; }
.ruler { position: absolute; inset: 0 0 auto; height: 18px; border-bottom: 1px solid #222a34; }
.ruler span { position: absolute; top: 3px; padding-left: 3px; border-left: 1px solid #3a4452; font: 9px Consolas, monospace; color: #6f7b8a; }
.wave { position: absolute; top: 20px; left: 0; height: 44px; }
.wave canvas { display: block; height: 44px; }
.beats { position: absolute; top: 20px; left: 0; right: 0; height: 64px; pointer-events: none; }
.beats i { position: absolute; top: 30px; width: 1px; height: 12px; background: #3a4452; }
.beats i.down { top: 0; height: 64px; background: #4d5a6a; opacity: .7; }
.beats em { position: absolute; top: 46px; transform: translateX(-50%); min-width: 15px; height: 15px; padding: 0 3px; border-radius: 8px; background: var(--accent); color: #1a1205; font: 700 9px/15px Consolas, monospace; text-align: center; font-style: normal; }
.shots { position: absolute; top: 92px; left: 0; right: 0; height: 74px; }
.shot { position: absolute; top: 8px; height: 58px; border: 1px solid #3e4b5b; border-radius: 5px; background-size: cover; background-position: center; overflow: hidden; cursor: pointer; }
.shot.sel { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.shot .name { position: absolute; left: 6px; bottom: 4px; right: 12px; font-size: 10px; color: #dfe5ec; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.shot .tr { position: absolute; left: 4px; top: 4px; padding: 0 5px; font-size: 9px; color: #1a1205; background: #9ad1ff; border-radius: 3px; }
.shot .end { position: absolute; right: 0; top: 0; bottom: 0; width: 8px; background: #ffffff22; cursor: ew-resize; }
.shot .end:hover { background: var(--accent); }
.kill { position: absolute; top: 0; z-index: 3; width: 13px; height: 13px; margin-left: -6.5px; padding: 0; border: 1px solid #0b0e13; border-radius: 2px; transform: rotate(45deg); background: #ff6b5e; cursor: ew-resize; }
.kill:hover { background: #ffa198; transform: rotate(45deg) scale(1.25); }
.drag-line { position: absolute; top: 18px; bottom: 0; width: 2px; margin-left: -1px; background: #ffa198; pointer-events: none; z-index: 5; }
.drag-line span { position: absolute; top: 0; left: 4px; padding: 1px 4px; font: 700 10px Consolas, monospace; color: #1a1205; background: #ffa198; border-radius: 3px; }
.playhead { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #4aa3ff; box-shadow: 0 0 6px #4aa3ffaa; pointer-events: none; z-index: 4; }
.errors { margin: 8px 0 0; padding: 6px 10px; list-style: none; font-size: 11px; color: #f0c674; background: #2a2213; border: 1px solid #5d4820; border-radius: 6px; }
.inspector { display: flex; align-items: center; gap: 10px; margin-top: 8px; padding: 7px 9px; border: 1px solid #343e4a; border-radius: 8px; background: #141a22; flex-wrap: wrap; font-size: 12px; }
.inspector label { display: flex; align-items: center; gap: 5px; color: #9ca7b4; font-size: 11px; }
.inspector select { padding: 3px 6px; font-size: 12px; max-width: 220px; }
.chip { padding: 3px 8px; color: #211706; background: var(--accent); border-radius: 5px; font-weight: 700; font-size: 11px; }
.file { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kills { display: flex; align-items: center; gap: 4px; color: #9ca7b4; font-size: 11px; }
.tiny { padding: 3px 8px; font-size: 11px; }
.foot { margin: 8px 2px 0; font-size: 11px; }
</style>
