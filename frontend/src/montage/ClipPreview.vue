<script setup>
// 素材预览：看一段素材，手动标击杀（开枪那一帧），给没有识别记录的视频用。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useMontage } from './store'
import { mapi } from './api'

const m = useMontage()
const video = ref(null)
const t = ref(0)

const item = computed(() => m.scan?.items.find(i => i.path === m.source) || { path: m.source, name: m.source?.split(/[\\/]/).pop() })
const clip = computed(() => m.clipMap[m.source])
const manual = computed(() => clip.value?.manual_kills || [])
const planned = computed(() => m.project?.clip_kills?.[m.source] || [])
const fmt = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(2).padStart(5, '0')}`

function mark() { m.setManualKills(m.source, [...manual.value, video.value.currentTime], item.value) }
function unmark(k) { m.setManualKills(m.source, manual.value.filter(x => x !== k), item.value) }
function go(s) { video.value.currentTime = s; video.value.pause() }

function onKey(e) {
  if (!video.value || e.ctrlKey || e.metaKey || e.altKey || e.target?.closest?.('input, textarea, select')) return
  const v = video.value
  if (e.key === ' ' && !e.target?.closest?.('button, video')) { e.preventDefault(); v.paused ? v.play() : v.pause() }
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); v.currentTime = Math.max(0, v.currentTime + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 1)) }
  else if (e.key === ',' || e.key === '.') { e.preventDefault(); v.pause(); v.currentTime = Math.max(0, v.currentTime + (e.key === ',' ? -1 : 1) / 60) }
  else if (e.key.toLowerCase() === 'm') { e.preventDefault(); mark() }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="cp">
    <div class="screen">
      <video ref="video" :src="mapi.fileUrl(m.source)" controls preload="auto" @timeupdate="t = video.currentTime"></video>
    </div>
    <div class="bar">
      <button class="ghost back" @click="m.source = null">← 回到成片预览</button>
      <span class="name" :title="item.path">{{ item.name }}</span>
      <span class="spacer"></span>
      <label class="use"><input type="checkbox" :checked="!!clip?.selected" @change="m.toggleClip(item, $event.target.checked)" /> 用这段素材</label>
      <button class="primary" title="快捷键 M" @click="mark">＋ 在这一帧标击杀</button>
    </div>
    <div class="kills">
      <span class="muted">手标击杀（停在开枪那一帧再标，<b>,</b> <b>.</b> 逐帧，M 标记）：</span>
      <button v-for="k in manual" :key="k" class="ghost tiny" @click="go(k)">{{ fmt(k) }} <i @click.stop="unmark(k)">✕</i></button>
      <span v-if="!manual.length" class="muted">无</span>
      <template v-if="planned.length && !manual.length">
        <span class="muted sep">自动识别：</span>
        <button v-for="k in planned" :key="'p' + k" class="ghost tiny auto" @click="go(k)">{{ fmt(k) }}</button>
      </template>
      <span v-else-if="item.auto_kills && !manual.length" class="muted sep">识别记录里有 {{ item.auto_kills }} 个击杀，编排时自动找开枪帧</span>
    </div>
  </div>
</template>

<style scoped>
.cp { display: flex; flex-direction: column; gap: 8px; }
.screen { aspect-ratio: 16 / 9; background: #000; border-radius: 8px; overflow: hidden; }
video { width: 100%; height: 100%; display: block; }
.bar { display: flex; align-items: center; gap: 10px; }
.back { padding: 5px 10px; font-size: 12px; }
.name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.use { display: flex; align-items: center; gap: 5px; font-size: 12px; white-space: nowrap; } .use input { accent-color: var(--accent); }
.bar .primary { padding: 6px 12px; white-space: nowrap; }
.kills { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 11px; }
.kills b { color: var(--text); }
.tiny { padding: 2px 7px; font-size: 11px; font-family: Consolas, monospace; }
.tiny i { font-style: normal; margin-left: 4px; color: var(--danger); }
.auto { color: #ff8a80; }
.sep { margin-left: 8px; }
</style>
