<script setup>
// 成片预览：浏览器里用歌当时钟，按时间线实时换素材、调播放速度。
// 只是近似预览（变速、转场效果以出片为准），用来快速看节奏和镜头顺序。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMontage } from './store'
import { mapi } from './api'

const m = useMontage()
const audio = ref(null)
const vids = [ref(null), ref(null)]
const front = ref(0)              // 正在显示的 video
const loaded = [null, null]       // 每个 video 当前载入的文件
const fx = ref('')                // 转场近似效果
const fxKey = ref(0)
let raf = 0
let lastShot = -1

const songUrl = computed(() => m.project?.song ? mapi.songUrl(m.project.id, m.project.song.name + m.project.song.duration) : '')
const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`

// 成片时间 T -> { shot, file, src, rate }
function locate(T) {
  const shots = m.shots
  const i = shots.findIndex(s => T < s.end)
  const si = i < 0 ? shots.length - 1 : i
  const s = shots[si]
  if (!s) return null
  let u = Math.max(0, T - s.start)
  for (const seg of s.segments || []) {
    const [a, b] = seg.src, [v0, v1] = seg.speed
    const d = 2 * (b - a) / (v0 + v1)
    if (u <= d || seg === s.segments.at(-1)) {
      const uu = Math.min(u, d), acc = (v1 - v0) / d
      return { index: si, shot: s, src: a + v0 * uu + 0.5 * acc * uu * uu, rate: v0 + acc * uu }
    }
    u -= d
  }
  return null
}

function ensure(k, file) {
  const v = vids[k].value
  if (v && loaded[k] !== file) { loaded[k] = file; v.src = mapi.fileUrl(file) }
  return v
}

function sync(seekTolerance) {
  const loc = locate(m.T)
  if (!loc) return
  let k = front.value
  if (loaded[k] !== loc.shot.file) {
    const other = 1 - k
    if (loaded[other] === loc.shot.file) k = other
    ensure(k, loc.shot.file)
    front.value = k
  }
  const v = vids[k].value
  if (!v) return
  if (Math.abs(v.currentTime - loc.src) > seekTolerance) v.currentTime = loc.src
  const rate = Math.max(0.25, Math.min(8, loc.rate))
  if (Math.abs(v.playbackRate - rate) > 0.01) v.playbackRate = rate
  if (m.playing && v.paused) v.play().catch(() => {})
  if (!m.playing && !v.paused) v.pause()
  // 下一个镜头提前载入到另一个 video
  const next = m.shots[loc.index + 1]
  if (next && loaded[1 - k] !== next.file) {
    const pre = ensure(1 - k, next.file)
    pre.currentTime = next.segments?.[0]?.src[0] || 0
  }
  if (loc.index !== lastShot) {
    if (lastShot >= 0 && m.playing) { fx.value = loc.shot.transition_in || 'cut'; fxKey.value++ }
    lastShot = loc.index
    m.selectedShot = m.playing ? loc.index : m.selectedShot
  }
}

function tick() {
  if (m.playing && audio.value) {
    m.T = audio.value.currentTime
    if (m.T >= m.duration - 0.02) { pause(); m.T = m.duration }
    sync(0.25)
  }
  raf = requestAnimationFrame(tick)
}

function play() {
  if (!m.shots.length || !audio.value) return
  if (m.T >= m.duration - 0.05) m.T = 0
  audio.value.currentTime = m.T
  m.playing = true
  audio.value.play().catch(() => { m.playing = false })
  sync(0.05)
}
function pause() {
  m.playing = false
  audio.value?.pause()
  vids.forEach(v => v.value?.pause())
}
function toggle() { m.playing ? pause() : play() }

// 停着时拖播放头：立即对齐画面和歌
watch(() => m.T, (T) => {
  if (m.playing) return
  if (audio.value && Math.abs(audio.value.currentTime - T) > 0.05) audio.value.currentTime = T
  sync(0.03)
})
watch(() => m.timeline, () => { lastShot = -1; if (!m.playing) sync(0.03) })
watch(() => m.source, (s) => { if (s) pause() })
watch(() => m.playing, (p) => { if (!p) pause() })

function onKey(e) {
  if (m.source || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return
  if (e.target?.closest?.('input, textarea, select, [contenteditable="true"]')) return
  if (e.key === ' ' && !e.target?.closest?.('button')) { e.preventDefault(); toggle() }
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); if (m.playing) pause(); m.stepBeat(e.key === 'ArrowLeft' ? -1 : 1, e.shiftKey) }
  else if (e.key === 'Home') { e.preventDefault(); m.T = 0 }
}
onMounted(() => { raf = requestAnimationFrame(tick); window.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { cancelAnimationFrame(raf); window.removeEventListener('keydown', onKey); pause() })
defineExpose({ toggle, pause })
</script>

<template>
  <div class="mp">
    <div class="screen" @click="toggle">
      <video v-for="(v, k) in vids" :key="k" :ref="el => (vids[k].value = el)" :class="{ on: front === k }" muted playsinline preload="auto"></video>
      <div v-if="fx && fx !== 'cut'" :key="fxKey" class="fx" :class="fx"></div>
      <div v-if="!m.shots.length" class="empty">
        <b>还没有时间线</b>
        <span>左边勾选素材，右边选一首歌，然后点「自动编排」</span>
      </div>
      <div v-else-if="!m.playing" class="hint">▶ 空格播放 · ← → 按拍移动（Shift 按小节）</div>
    </div>
    <audio ref="audio" :src="songUrl" preload="auto"></audio>
    <div class="bar">
      <button class="primary play" :disabled="!m.shots.length" @click="toggle">{{ m.playing ? '❚❚ 暂停' : '▶ 播放' }}</button>
      <span class="t">{{ fmt(m.T) }} / {{ fmt(m.duration) }}</span>
      <span v-if="m.song" class="muted bpm">{{ m.song.bpm }} BPM</span>
      <span class="spacer"></span>
      <span class="muted note">预览是近似效果，变速和转场以出片为准</span>
    </div>
  </div>
</template>

<style scoped>
.mp { display: flex; flex-direction: column; gap: 8px; }
.screen { position: relative; aspect-ratio: 16 / 9; background: #000; border-radius: 8px; overflow: hidden; cursor: pointer; }
video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; opacity: 0; }
video.on { opacity: 1; }
.empty { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: var(--muted); font-size: 13px; }
.empty b { color: var(--text); font-size: 15px; }
.hint { position: absolute; left: 10px; bottom: 8px; padding: 3px 8px; font-size: 11px; color: #cfd6df; background: #000a; border-radius: 4px; pointer-events: none; }
.bar { display: flex; align-items: center; gap: 10px; }
.play { min-width: 84px; padding: 6px 12px; }
.t { font: 12px Consolas, monospace; font-variant-numeric: tabular-nums; }
.bpm, .note { font-size: 11px; }
.fx { position: absolute; inset: 0; pointer-events: none; }
.fx.flash, .fx.impact { background: #fff; animation: fade .3s ease-out forwards; }
.fx.dip { background: #000; animation: fade .3s ease-out forwards; }
.fx.push, .fx.whip { backdrop-filter: blur(6px); animation: fade .3s ease-out forwards; }
@keyframes fade { from { opacity: .85; } to { opacity: 0; } }
</style>
