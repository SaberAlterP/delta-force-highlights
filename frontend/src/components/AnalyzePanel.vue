<script setup>
import { ref, computed } from 'vue'
import { useStore } from '../store'

const store = useStore()
const showAdvanced = ref(false)

const canAnalyze = computed(() =>
  !!store.video && store.analyze.state !== 'running'
)

const keywordsText = computed({
  get: () => store.config.knockdown_keywords.join('、'),
  set: (v) => {
    store.config.knockdown_keywords = v
      .split(/[、,，\s]+/).map(s => s.trim()).filter(Boolean)
  },
})

// 区域编辑：用百分比展示，便于阅读
function regLabel(name) {
  return name === 'id_region' ? '右上角 ID 区域' : '准星下方击倒提示区域'
}
function pct(v) { return Math.round(v * 1000) / 10 }
function setReg(name, idx, val) {
  const arr = [...store.regions[name]]
  arr[idx] = Math.min(1, Math.max(0, Number(val) / 100))
  store.regions[name] = arr
  store.saveRegions()
}
</script>

<template>
  <div class="panel">
    <h2>识别击杀</h2>

    <label class="field">
      <span>你的游戏 ID <span class="muted">(右上角击杀信息里显示的名字)</span></span>
      <input
        :value="store.playerId"
        @input="store.setPlayerId($event.target.value)"
        placeholder="击杀信息里显示的名字"
      />
    </label>
    <p class="hint muted">
      右上角击杀信息独立扫描，并核对击杀者与被击杀者。中间提示补充候选；连续击杀逐人记录，同一人的击倒、补杀只算一次。待复核候选默认不勾选。
    </p>

    <div class="row" style="margin-top:6px">
      <label class="chk">
        <input type="checkbox" v-model="store.showRegions" />
        在播放器上显示检测区域
      </label>
      <span class="spacer"></span>
      <button class="ghost small-btn" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起高级设置 ▲' : '高级设置 ▼' }}
      </button>
    </div>

    <div v-if="showAdvanced" class="advanced">
      <div class="adv-row">
        <label>采样帧率 (fps)
          <input type="number" min="1" max="10" step="0.5" v-model.number="store.config.sample_fps" />
        </label>
        <label>同一提示去重 (秒)
          <input type="number" min="1" max="15" step="0.5" v-model.number="store.config.debounce_seconds" />
        </label>
        <label>ID 匹配阈值
          <input type="number" min="0.3" max="1" step="0.05" v-model.number="store.config.id_match_ratio" />
        </label>
      </div>

      <label class="field" style="margin-top:10px">
        <span>击倒关键词 <span class="muted">(顿号/逗号分隔，默认 6 个)</span></span>
        <input v-model="keywordsText" />
      </label>

      <div v-for="name in ['id_region','prompt_region']" :key="name" class="region-edit">
        <div class="region-title">{{ regLabel(name) }} <span class="muted">(% 占比)</span></div>
        <div class="region-inputs">
          <label>左 <input type="number" :value="pct(store.regions[name][0])" @input="setReg(name,0,$event.target.value)" /></label>
          <label>上 <input type="number" :value="pct(store.regions[name][1])" @input="setReg(name,1,$event.target.value)" /></label>
          <label>右 <input type="number" :value="pct(store.regions[name][2])" @input="setReg(name,2,$event.target.value)" /></label>
          <label>下 <input type="number" :value="pct(store.regions[name][3])" @input="setReg(name,3,$event.target.value)" /></label>
        </div>
      </div>
    </div>

    <button class="primary analyze-btn" :disabled="!canAnalyze" @click="store.runAnalyze()">
      {{ store.analyze.state === 'running' ? '识别中…' : '🔍 开始识别' }}
    </button>

    <div v-if="store.analyze.state === 'running'" class="prog">
      <div class="progress"><i :style="{ width: (store.analyze.progress*100) + '%' }"></i></div>
      <div class="muted small">{{ store.analyze.message || '处理中…' }} ({{ Math.round(store.analyze.progress*100) }}%)</div>
    </div>
    <div v-else-if="store.analyze.state === 'done'" class="done">
      ✅ 识别完成，共 <b>{{ store.kills.length }}</b> 次击杀
      <div v-if="store.analyze.message" class="stats" role="status">
        <span>识别诊断</span>
        <p>{{ store.analyze.message }}</p>
      </div>
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
