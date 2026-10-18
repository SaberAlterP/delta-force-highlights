<script setup>
import { computed, ref } from 'vue'
import { useStore } from '../store'
import { api } from '../api'
import { fmtTime } from '../util'

const store = useStore()
const merge = ref(false)
const accurate = ref(false)
const stretch = computed({ get: () => store.stretch169, set: (v) => store.setStretch169(v) })

const segments = computed(() => store.exportSegments)
const total = computed(() => segments.value.reduce((n, s) => n + s.end - s.start, 0))
const busy = computed(() => store.export.state === 'running')
const isArchive = computed(() => !!store.video?.workflow_id)
// 只显示针对当前素材的导出结果
const result = computed(() => store.export.uploadId === store.video?.upload_id ? store.export : null)
const jobId = computed(() => store.export.jobId)

function run() { store.runExport({ merge: merge.value, accurate: accurate.value, stretch: stretch.value }) }
function openFolder() { api.workflowOpenFolder(store.video.workflow_id).catch(() => {}) }
</script>

<template>
  <div class="panel">
    <h2>导出片段 <span class="badge">{{ segments.length }} / {{ store.segments.length }}</span></h2>
    <p class="muted dest">
      <template v-if="isArchive">保存到这局集锦文件夹里的「手动剪辑」，可以在上方素材标签里直接播放。</template>
      <template v-else>手动上传的录像没有集锦文件夹，导出后在下面下载。</template>
    </p>

    <p v-if="!store.segments.length" class="muted empty">这段素材还没有片段。在时间轴上点「在当前位置建片段」。</p>
    <p v-else-if="!segments.length" class="muted empty">片段都没勾选。在「片段」列表里勾选要导出的片段。</p>
    <template v-else>
      <ol class="picked">
        <li v-for="s in segments" :key="s.id"><span>{{ s.label || '片段' }}</span><em>{{ fmtTime(s.start) }}–{{ fmtTime(s.end) }}</em></li>
      </ol>
      <p class="muted sum">共 {{ segments.length }} 段，{{ total.toFixed(1) }} 秒</p>

      <div class="opts">
        <label class="chk"><input type="checkbox" v-model="merge" :disabled="segments.length < 2" /> 合并成一个视频</label>
        <label class="chk"><input type="checkbox" v-model="stretch" /> 拉伸成 16:9</label>
        <label class="chk"><input type="checkbox" v-model="accurate" /> 精确剪辑<small>（重新编码，起止更准但更慢）</small></label>
      </div>

      <button class="primary export-btn" :disabled="busy" @click="run">
        {{ busy ? '导出中…' : merge && segments.length > 1 ? `合并 ${segments.length} 段并保存` : `保存 ${segments.length} 段` }}
      </button>
    </template>

    <div v-if="result && result.state === 'running'" class="prog">
      <div class="progress"><i :style="{ width: (result.progress * 100) + '%' }"></i></div>
      <div class="muted small">{{ result.message }}（{{ Math.round(result.progress * 100) }}%）</div>
    </div>
    <p v-if="result?.error" class="err">{{ result.error }}</p>

    <div v-if="result?.state === 'done'" class="results">
      <div class="done">✓ 已保存 {{ result.files.length }} 个片段{{ result.hasMerged ? '和 1 个合并视频' : '' }}</div>
      <button v-if="isArchive" class="ghost" @click="openFolder">打开集锦文件夹</button>
      <template v-else>
        <div class="row dl-actions">
          <a v-if="result.files.length > 1" class="dl" :href="api.exportZipUrl(jobId)" download>打包下载 ZIP</a>
          <a v-if="result.hasMerged" class="dl" :href="api.exportMergedUrl(jobId)" download>下载合并视频</a>
        </div>
        <a v-for="f in result.files" :key="f.name" class="file" :href="api.exportFileUrl(jobId, f.name)" download>{{ f.name }}</a>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dest { font-size: 12px; line-height: 1.7; margin: 0 0 10px; }
.empty { font-size: 12px; line-height: 1.7; margin: 0; }
.picked { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow-y: auto; counter-reset: n; }
.picked li { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; padding: 5px 8px; background: var(--panel-2); border-radius: 6px; counter-increment: n; }
.picked li span::before { content: counter(n) '. '; color: var(--muted); }
.picked em { font-style: normal; color: var(--muted); font-variant-numeric: tabular-nums; }
.sum { font-size: 11px; margin: 6px 0 10px; }
.opts { display: flex; flex-direction: column; gap: 7px; margin-bottom: 12px; }
.chk { display: flex; align-items: center; gap: 7px; font-size: 13px; }
.chk small { color: var(--muted); font-size: 11px; }
.chk input { accent-color: var(--accent); }
.export-btn { width: 100%; }
.prog { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.small { font-size: 12px; }
.err { color: var(--danger); font-size: 12px; margin-top: 10px; }
.results { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.done { color: var(--ok); font-size: 13px; }
.dl-actions { gap: 8px; }
.dl { text-decoration: none; color: #1a1205; background: var(--accent); padding: 7px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; }
.file { text-decoration: none; color: var(--text); font-size: 12px; padding: 7px 9px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file:hover { border-color: var(--accent); }
</style>
