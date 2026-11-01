<script setup>
import { computed } from 'vue'
import { useStore } from '../store'

const store = useStore()
const canAnalyze = computed(() => !!store.video && store.analyze.state !== 'running')
</script>

<template>
  <div class="panel">
    <h2>读取官方击杀记录</h2>
    <p class="hint muted">
      按录像的原文件名（例如 record20261018-201500.mp4）在 WeGame「精彩时刻」里找这局的击杀、摸金记录，不做画面识别。
      读不到时可以直接在时间轴上手动建片段。
    </p>

    <button class="primary analyze-btn" :disabled="!canAnalyze" @click="store.runAnalyze()">
      {{ store.analyze.state === 'running' ? '读取中…' : '读取官方记录' }}
    </button>

    <div v-if="store.analyze.state === 'running'" class="prog">
      <div class="progress"><i :style="{ width: (store.analyze.progress*100) + '%' }"></i></div>
      <div class="muted small">{{ store.analyze.message || '处理中…' }}</div>
    </div>
    <div v-else-if="store.analyze.state === 'done'" class="done">
      ✅ {{ store.analyze.message || `读到 ${store.kills.length} 个标记` }}
    </div>
    <p v-if="store.analyze.error" class="err">{{ store.analyze.error }}</p>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 4px; }
.field span { font-size: 13px; }
.hint { font-size: 12px; line-height: 1.5; margin: 6px 0 4px; }
.stats { margin-top: 8px; padding: 8px 10px; border: 1px solid #344150; border-radius: 7px; background: #151b22; line-height: 1.45; }
.stats span { color: var(--accent); font: 700 9px Consolas, monospace; letter-spacing: .12em; }
.stats p { margin: 3px 0 0; color: #9eabba; font-size: 11px; }
.chk { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.small-btn { padding: 5px 10px; font-size: 12px; }
.advanced {
  margin: 12px 0; padding: 12px;
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px;
}
.adv-row { display: flex; gap: 10px; flex-wrap: wrap; }
.adv-row label, .region-inputs label {
  display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted);
}
.adv-row input { width: 84px; }
.region-edit { margin-top: 12px; }
.region-title { font-size: 12px; margin-bottom: 6px; }
.region-inputs { display: flex; gap: 8px; }
.region-inputs input { width: 56px; }
.analyze-btn { width: 100%; margin-top: 14px; }
.prog { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.small { font-size: 12px; }
.done { margin-top: 12px; color: var(--ok); font-size: 13px; }
.err { color: var(--danger); font-size: 12px; margin-top: 10px; }
</style>
