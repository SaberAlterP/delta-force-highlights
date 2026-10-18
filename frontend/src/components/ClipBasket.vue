<script setup>
import { ref, computed } from 'vue'
import { useStore } from '../store'
import { api } from '../api'
import { fmtTime } from '../util'

const store = useStore()
const merge = ref(false)
const accurate = ref(false)
const stretch = computed({
  get: () => store.stretch169,
  set: (value) => store.setStretch169(value),
})

const groups = computed(() => store.basketByVideo)
const count = computed(() => store.basket.length)
const busy = computed(() => store.export.state === 'running')

function bRange(b) { return store.basketRange(b) }
async function go(b) {
  try { await store.openSource(b.upload_id); store.requestSeek(b.time) }
  catch (e) { window.alert(e?.response?.data?.detail || e.message || '这段素材已不存在') }
}
function run() { store.runExport({ merge: merge.value, accurate: accurate.value, stretch: stretch.value }) }

const jobId = computed(() => store.export.jobId)
function fileUrl(name) { return api.exportFileUrl(jobId.value, name) }
const mergedUrl = computed(() => api.exportMergedUrl(jobId.value))
const zipUrl = computed(() => api.exportZipUrl(jobId.value))
</script>

<template>
  <div class="panel">
    <h2>导出片段
      <span class="badge" style="margin-left:6px">{{ count }} 个片段</span>
    </h2>

    <div class="opts">
      <label class="chk"><input type="checkbox" v-model="stretch" /> 拉伸为 16:9（预览和导出）</label>
      <span class="muted small">真正拉伸像素；整局原片保持原样。</span>
    </div>

    <div v-if="count === 0" class="muted empty">
      导出列表是空的。在「片段」里点「加入导出」，可以把多局的片段放在一起导出。
    </div>

    <template v-else>
      <div class="groups scroll">
        <div v-for="(g, uid) in groups" :key="uid" class="group">
          <div class="g-title" :title="g.filename">🎬 {{ g.filename }}</div>
          <div v-for="b in g.items" :key="b.bid" class="bitem">
            <div class="b-primary">
              <button class="b-time" @click="go(b)" title="切到该视频并跳转">⏱ {{ fmtTime(b.time) }}</button>
              <input class="b-label" v-model="b.label" placeholder="片段标题"
                     @change="store.updateBasketItem(b.bid, { label: b.label })" />
            </div>
            <div class="b-meta">
              <span class="b-range muted">{{ fmtTime(bRange(b).start) }}–{{ fmtTime(bRange(b).end) }}</span>
              <label class="pp">前<input type="number" min="0" max="120" v-model.number="b.pre"
                     @change="store.updateBasketItem(b.bid, { pre: b.pre })" />s</label>
              <label class="pp">后<input type="number" min="0" max="60" v-model.number="b.post"
                     @change="store.updateBasketItem(b.bid, { post: b.post })" />s</label>
            </div>
            <button class="b-del danger ghost" @click="store.removeFromBasket(b.bid)" title="删除这个片段" aria-label="删除这个片段">✕</button>
          </div>
        </div>
      </div>

      <div class="opts">
        <label class="chk"><input type="checkbox" v-model="merge" /> 合并为一个集锦视频</label>
        <label class="chk"><input type="checkbox" v-model="accurate" /> 精确剪辑（重编码，慢但起止精确）</label>
      </div>

      <div class="row actions">
        <button class="primary export-btn" :disabled="busy" @click="run">
          {{ busy ? '导出中…' : `⬇ 导出 ${count} 个片段` }}
        </button>
        <button class="ghost" :disabled="busy" @click="store.clearBasket()">清空</button>
      </div>

      <div v-if="busy" class="prog">
        <div class="progress"><i :style="{ width: (store.export.progress*100) + '%' }"></i></div>
        <div class="muted small">{{ store.export.message }} ({{ Math.round(store.export.progress*100) }}%)</div>
      </div>
      <p v-if="store.export.error" class="err">{{ store.export.error }}</p>

      <div v-if="store.export.state === 'done'" class="results">
        <div class="done">✅ 导出完成</div>
        <div class="row dl-actions">
          <a v-if="store.export.files.length > 1" class="dl-all" :href="zipUrl" download>📦 打包下载 (ZIP)</a>
          <a v-if="store.export.hasMerged" class="dl-all" :href="mergedUrl" download>🎬 下载合并集锦</a>
        </div>
        <div class="files scroll">
          <a v-for="f in store.export.files" :key="f.name" class="file" :href="fileUrl(f.name)" download>
            🎞 {{ f.name }}
          </a>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.empty { font-size: 13px; line-height: 1.6; padding: 8px 0; }
.groups { display: flex; flex-direction: column; gap: 10px; max-height: 340px; margin-bottom: 12px; overflow-x: hidden; }
.group { min-width: 0; }
.g-title { font-size: 12px; color: var(--accent-2); margin-bottom: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bitem {
  display: grid; grid-template-columns: minmax(0, 1fr) 34px; grid-template-rows: auto auto;
  grid-template-areas: "primary delete" "meta delete"; align-items: center; gap: 6px 8px;
  min-width: 0; padding: 8px; margin-bottom: 6px;
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px;
}
.b-primary { grid-area: primary; display: flex; align-items: center; gap: 6px; min-width: 0; }
.b-meta { grid-area: meta; display: flex; align-items: center; gap: 7px; min-width: 0; flex-wrap: wrap; }
.b-time { flex: none; padding: 4px 7px; font-size: 11px; font-variant-numeric: tabular-nums; }
.b-label { min-width: 0; flex: 1; width: 100%; padding-block: 5px; }
.b-range { font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pp { display: flex; align-items: center; gap: 2px; font-size: 11px; color: var(--muted); white-space: nowrap; }
.pp input { width: 48px; padding: 3px 4px; font-variant-numeric: tabular-nums; }
.b-del {
  grid-area: delete; align-self: stretch; width: 34px; padding: 0;
  display: grid; place-items: center; font-size: 16px; border-radius: 7px;
}
.opts { display: flex; flex-direction: column; gap: 7px; margin-bottom: 12px; }
.chk { display: flex; align-items: center; gap: 7px; font-size: 13px; }
.actions { gap: 8px; }
.export-btn { flex: 1; }
.prog { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.small { font-size: 12px; }
.err { color: var(--danger); font-size: 12px; margin-top: 10px; }
.results { margin-top: 14px; }
.done { color: var(--ok); font-size: 13px; margin-bottom: 10px; }
.dl-actions { margin-bottom: 10px; gap: 8px; }
.dl-all { text-decoration: none; color: #1a1205; background: var(--accent); padding: 7px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; }
.dl-all:hover { background: var(--accent-2); }
.files { display: flex; flex-direction: column; gap: 6px; max-height: 200px; }
.file {
  text-decoration: none; color: var(--text); font-size: 12px; padding: 7px 9px;
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.file:hover { border-color: var(--accent); }

@media (max-width: 1320px) {
  .b-range { width: 100%; }
}
</style>
