<script setup>
import { computed } from 'vue'
import { useStore } from '../store'
import { fmtTime } from '../util'

const store = useStore()
const kills = computed(() => store.sortedKills)
const segments = computed(() => [...store.segments].sort((a, b) => a.start - b.start))
const pending = computed(() => segments.value.filter(s => !store.segmentInBasket(s.id)).length)

function kind(k) {
  if (k.event_type === 'loot') return ['摸金', 'loot']
  if (['vehicle', 'other'].includes(k.event_type)) return ['其他', 'other']
  if (k.source === 'wegame') return ['官方击杀', 'kill']
  return k.review_required ? ['待确认', 'review'] : ['击杀', 'kill']
}
function addFrom(k) { store.addSegmentAt(k.time); store.requestSeek(Math.max(0, k.time - 3)) }
</script>

<template>
  <div class="panel lists">
    <section>
      <h2>片段 <span class="badge">{{ segments.length }}</span>
        <button v-if="pending" class="ghost head-btn" @click="store.addAllSegmentsToBasket()">全部加入导出列表</button>
      </h2>
      <p v-if="!segments.length" class="muted empty">还没有片段。在时间轴上点「在当前位置建片段」，或在下面的击杀标记旁点「建片段」。</p>
      <div v-else class="rows scroll">
        <div v-for="(s, i) in segments" :key="s.id" class="row-item">
          <span class="idx">{{ i + 1 }}</span>
          <button class="time" @click="store.requestSeek(s.start)">{{ fmtTime(s.start) }} – {{ fmtTime(s.end) }}</button>
          <span class="muted dur">{{ (s.end - s.start).toFixed(1) }}s</span>
          <input class="label" :value="s.label" placeholder="片段名（可选）" @change="store.updateSegment(s.id, { label: $event.target.value })" />
          <button v-if="store.segmentInBasket(s.id)" class="ghost act ok" disabled>✓ 已加入</button>
          <button v-else class="ghost act" @click="store.addSegmentToBasket(s)">加入导出</button>
          <button class="danger ghost act" title="删除片段" @click="store.removeSegment(s.id)">✕</button>
        </div>
      </div>
    </section>

    <section>
      <h2>击杀标记 <span class="badge">{{ kills.length }}</span>
        <button class="ghost head-btn" @click="store.addManualKill(store.currentTime)">＋ 在当前时间加标记</button>
      </h2>
      <p v-if="!kills.length" class="muted empty">没有标记。识别完成后会显示在这里，只用来标注位置，不会自动变成片段。</p>
      <div v-else class="rows scroll">
        <div v-for="(k, i) in kills" :key="k.id" class="row-item">
          <span class="idx">{{ i + 1 }}</span>
          <button class="time" @click="store.requestSeek(k.time)">⏱ {{ fmtTime(k.time) }}</button>
          <span class="tag" :class="kind(k)[1]" :title="k.victim_id || k.prompt_text || ''">{{ kind(k)[0] }}</span>
          <input class="label" v-model="k.label" placeholder="备注（可选）" @change="store.persistKills()" />
          <button class="ghost act" title="以这个标记为中心建一个片段" @click="addFrom(k)">建片段</button>
          <button class="danger ghost act" title="删除标记" @click="store.removeKill(k.id)">✕</button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lists { display: flex; flex-direction: column; gap: 16px; }
h2 { margin-bottom: 8px; }
.head-btn { margin-left: auto; padding: 4px 10px; font-size: 12px; font-weight: 400; }
.empty { font-size: 12px; line-height: 1.7; margin: 0; }
.rows { display: flex; flex-direction: column; gap: 5px; max-height: 260px; }
.row-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; }
.idx { color: var(--muted); font: 11px Consolas, monospace; width: 20px; }
.time { padding: 4px 8px; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.dur { font-size: 11px; width: 42px; }
.label { flex: 1; min-width: 60px; padding: 5px 8px; font-size: 12px; }
.act { padding: 4px 9px; font-size: 12px; white-space: nowrap; }
.act.ok { color: var(--ok); }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); white-space: nowrap; }
.tag.kill { color: #ff8c82; border-color: #5a2a26; } .tag.loot { color: #7cbcff; border-color: #22405e; }
.tag.review { color: var(--accent); border-color: #4a3a14; } .tag.other { color: var(--muted); }
</style>
