<script setup>
import { computed } from 'vue'
import { useStore } from '../store'
import { fmtTime } from '../util'

const store = useStore()
const kills = computed(() => store.sortedKills)
const allSelected = computed({
  get: () => kills.value.length > 0 && kills.value.every(k => k.selected),
  set: (v) => store.setSelectedAll(v),
})

function range(k) { return store.clipRange(k) }
function addSelected() {
  const n = store.addSelectedToBasket()
  if (n === 0) window.alert('勾选的片段都已在剪辑列表里了')
}
</script>

<template>
  <div class="panel">
    <h2>击杀标记
      <span class="badge" style="margin-left:6px">{{ kills.length }} 个</span>
    </h2>

    <div v-if="kills.length === 0" class="muted empty">
      暂无击杀标记。完成识别后会显示在这里，也可在播放器用「＋ 在当前时间添加击杀」手动添加。
    </div>

    <template v-else>
      <div class="row head">
        <label class="chk"><input type="checkbox" v-model="allSelected" /> 全选</label>
        <button class="primary add-sel" @click="addSelected">➕ 把勾选的加入剪辑列表</button>
      </div>

      <div class="list scroll">
        <div v-for="(k, i) in kills" :key="k.id" class="kill" :class="{ off: !k.selected }">
          <input type="checkbox" v-model="k.selected" @change="store.persistKills()" />
          <span class="idx">#{{ i + 1 }}</span>

          <button class="time-btn" @click="store.requestSeek(k.time)" :title="'跳转到 ' + fmtTime(k.time)">
            ⏱ {{ fmtTime(k.time) }}
          </button>

          <span class="conf badge" :class="{ ok: k.confidence >= 0.8, warn: k.confidence < 0.6 }"
                :title="k.source === 'wegame' ? k.prompt_text + '\n' + k.id_text : '右上角OCR: ' + k.id_text + '\n中间OCR: ' + k.prompt_text">
            {{ k.source === 'wegame' ? '官方时刻' : Math.round(k.confidence * 100) + '%' }}
          </span>

          <span class="badge" :title="k.victim_id || '被击杀者未确认'">
            {{ ['loot','vehicle','other'].includes(k.event_type) ? '非击杀' : k.review_required ? '待复核' : '已确认干员' }}
          </span>

          <input class="label" v-model="k.label" placeholder="标题(可选)" @change="store.persistKills()" />

          <span class="clip muted">{{ fmtTime(range(k).start) }}–{{ fmtTime(range(k).end) }}</span>

          <label class="pp">前<input type="number" min="0" max="120" v-model.number="k.pre" @change="store.updateKill(k.id, { pre: k.pre })" />s</label>
          <label class="pp">后<input type="number" min="0" max="60" v-model.number="k.post" @change="store.updateKill(k.id, { post: k.post })" />s</label>

          <button v-if="store.inBasket(k.id)" class="add added" disabled title="已在剪辑列表">✓</button>
          <button v-else class="add ghost" @click="store.addToBasket(k)" title="加入剪辑列表">➕</button>

          <button class="del danger ghost" @click="store.removeKill(k.id)" title="删除">✕</button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.empty { font-size: 13px; line-height: 1.6; padding: 8px 0; }
.head { margin-bottom: 8px; gap: 12px; }
.add-sel { padding: 6px 12px; font-size: 12px; margin-left: auto; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.list { max-height: 320px; display: flex; flex-direction: column; gap: 6px; }
.kill {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 8px; background: var(--panel-2);
  border: 1px solid var(--border); border-radius: 8px;
}
.kill.off { opacity: .5; }
.idx { color: var(--muted); font-size: 12px; width: 26px; }
.time-btn { padding: 4px 8px; font-size: 12px; font-variant-numeric: tabular-nums; }
.conf { min-width: 38px; text-align: center; }
.label { flex: 1; min-width: 60px; }
.clip { font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pp { display: flex; align-items: center; gap: 3px; font-size: 11px; color: var(--muted); white-space: nowrap; }
.pp input { width: 46px; padding: 4px 5px; }
.add { padding: 4px 8px; }
.add.added { color: var(--ok); border-color: #1f3d27; cursor: default; }
.del { padding: 4px 8px; }
</style>
