<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { capi, compress, isBusy, pickFile, setSource, start, cancel, errText, fmtSize, fmtDuration } from '../compress'

const LS_PRESET = 'df.compress.preset'
const LS_TARGET = 'df.compress.targetMb'
const presets = ref([])
const outputDir = ref('')
const preset = ref(localStorage.getItem(LS_PRESET) || 'share')
const targetMb = ref(Number(localStorage.getItem(LS_TARGET)) || 25)
const picking = ref(false)
const pickError = ref('')
watch(preset, v => localStorage.setItem(LS_PRESET, v))
watch(targetMb, v => { if (v > 0) localStorage.setItem(LS_TARGET, String(v)) })

onMounted(async () => {
  try { const r = await capi.presets(); presets.value = r.presets; outputDir.value = r.output_dir } catch { /* 后端离线时 App 顶部会提示 */ }
})

const busy = computed(() => isBusy())
const info = computed(() => compress.info)
const result = computed(() => compress.result)
const saved = computed(() => result.value ? 1 - result.value.ratio : 0)
// 指定大小时提示：目标比原文件还大就没必要压
const targetTooBig = computed(() => preset.value === 'target' && info.value && targetMb.value * 1024 * 1024 >= info.value.size)

async function choose() {
  picking.value = true; pickError.value = ''
  try { await pickFile() } catch (e) { pickError.value = errText(e, '无法打开选择窗口') }
  finally { picking.value = false }
}
function go() { start(preset.value, preset.value === 'target' ? Number(targetMb.value) : 0) }
function again() { setSource(compress.source, compress.label) }
function openFolder() { capi.openFolder(compress.jobId).catch(() => {}) }
</script>

<template>
  <div class="compress">
    <p class="muted intro">把视频重新压成小文件，方便发微信 / QQ 给别人看。整局原片、高光、手动剪辑、上传的录像、集锦成片都可以压；原文件不会被改动。</p>

    <!-- 1. 选视频 -->
    <section class="src">
      <div v-if="compress.source" class="picked">
        <div class="name">
          <b>{{ compress.label || info?.name || '视频' }}</b>
          <span v-if="info" class="muted">{{ info.name !== compress.label && compress.source.kind !== 'upload' ? info.name + ' · ' : '' }}{{ fmtSize(info.size) }} · {{ info.width }}×{{ info.height }} · {{ Math.round(info.fps) }} 帧 · {{ fmtDuration(info.duration) }}</span>
          <span v-else-if="compress.infoError" class="bad">{{ compress.infoError }}</span>
          <span v-else class="muted">正在读取视频信息…</span>
        </div>
        <button class="ghost" :disabled="busy || picking" @click="choose">换一个</button>
      </div>
      <div v-else class="empty">
        <p>还没选视频。可以在「自动剪素材」里打开一局，点「压缩这个视频」；也可以直接挑电脑上的文件。</p>
      </div>
      <button v-if="!compress.source" class="primary" :disabled="picking" @click="choose">{{ picking ? '在弹出的窗口里选择…' : '选择电脑上的视频…' }}</button>
      <p v-if="pickError" class="bad small">{{ pickError }}</p>
    </section>

    <!-- 2. 选档位 -->
    <section v-if="compress.source && !result">
      <h3>压成多大</h3>
      <div class="presets" role="radiogroup">
        <label v-for="p in presets" :key="p.key" class="preset" :class="{ on: preset === p.key }">
          <input type="radio" name="preset" :value="p.key" v-model="preset" :disabled="busy" />
          <b>{{ p.label }}</b>
          <span class="muted">{{ p.hint }}</span>
          <span v-if="p.key === 'target' && preset === 'target'" class="target" @click.stop>
            <input type="number" min="1" step="1" v-model.number="targetMb" :disabled="busy" aria-label="目标大小（MB）" /> MB
            <button v-for="n in [10, 25, 50, 100]" :key="n" type="button" class="ghost tiny" :class="{ on: targetMb === n }" :disabled="busy" @click="targetMb = n">{{ n }}</button>
          </span>
        </label>
      </div>
      <p v-if="targetTooBig" class="muted small">原文件只有 {{ fmtSize(info.size) }}，已经比目标小了，可以直接发原文件。</p>

      <button v-if="!busy" class="primary go" :disabled="!info || (preset === 'target' && !(targetMb > 0))" @click="go">开始压缩</button>
      <div v-else class="running" role="status">
        <div class="progress"><i :style="{ width: Math.max(3, compress.progress * 100) + '%' }"></i></div>
        <div class="row"><span class="muted small">{{ compress.message }}</span><span class="spacer"></span>
          <button class="ghost tiny" :disabled="compress.state === 'cancelling'" @click="cancel">取消</button></div>
        <p class="muted small">关掉这个窗口也会继续压，顶部「压缩视频」按钮会显示进度。</p>
      </div>
      <p v-if="compress.error" class="bad small" role="alert">{{ compress.error }}</p>
      <p v-if="compress.state === 'cancelled'" class="muted small">已取消，没有留下半截文件。</p>
    </section>

    <!-- 3. 结果 -->
    <section v-if="result" class="result">
      <h3>压好了</h3>
      <div class="sizes">
        <span class="before">{{ fmtSize(result.src_size) }}</span>
        <span class="arrow">→</span>
        <b class="after">{{ fmtSize(result.size) }}</b>
        <span v-if="saved > 0" class="ok">小了 {{ Math.round(saved * 100) }}%</span>
        <span v-else class="bad">没变小</span>
      </div>
      <p class="muted small">{{ result.src_width }}×{{ result.src_height }} → {{ result.width }}×{{ result.height }} · 用时 {{ result.seconds }} 秒（{{ result.encoder === 'h264_nvenc' ? '显卡编码' : 'CPU 编码' }}）</p>
      <p v-if="saved <= 0" class="muted small">原视频已经压得很小了，直接发原文件就行。</p>
      <p v-if="result.over_target" class="bad small">尽力压了两次还是比目标大一点，可以把目标再调小一些重压。</p>
      <video :src="capi.fileUrl(compress.jobId)" controls preload="metadata"></video>
      <div class="row">
        <a class="dl" :href="capi.fileUrl(compress.jobId, true)" download>下载</a>
        <button class="ghost" @click="openFolder">打开所在文件夹</button>
        <span class="spacer"></span>
        <button class="ghost" @click="again">换个档位重压</button>
      </div>
      <p class="muted small path">保存在：{{ result.path }}</p>
    </section>

    <p v-if="outputDir && !result" class="muted small foot">压缩后的文件放在：{{ outputDir }}</p>
  </div>
</template>

<style scoped>
.compress { display: flex; flex-direction: column; gap: 14px; padding: 12px 0 20px; }
.intro { margin: 0; font-size: 12px; line-height: 1.7; }
section { display: flex; flex-direction: column; gap: 10px; }
h3 { margin: 0; font-size: 13px; color: var(--accent-2); }
.small { font-size: 12px; margin: 0; }
.bad { color: #f0a6a8; }
.ok { color: var(--ok); font-size: 13px; }
.picked { display: flex; align-items: center; gap: 12px; padding: 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; }
.picked .name { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; font-size: 12px; overflow-wrap: anywhere; }
.picked b { font-size: 14px; }
.empty p { margin: 0; font-size: 12px; line-height: 1.7; color: var(--muted); }
.presets { display: flex; flex-direction: column; gap: 8px; }
.preset { display: grid; grid-template-columns: auto auto 1fr; align-items: center; gap: 4px 10px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; background: var(--panel-2); }
.preset.on { border-color: var(--accent); background: #f5a6230f; }
.preset input[type=radio] { accent-color: var(--accent); margin: 0; }
.preset .muted { font-size: 12px; }
.target { grid-column: 2 / -1; display: flex; align-items: center; gap: 6px; font-size: 12px; flex-wrap: wrap; }
.target input { width: 80px; padding: 5px 7px; }
.tiny { padding: 3px 9px; font-size: 11px; }
.tiny.on { border-color: var(--accent); color: var(--accent); }
.go { align-self: flex-start; padding: 9px 22px; }
.running { display: flex; flex-direction: column; gap: 6px; }
.sizes { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.sizes .before { color: var(--muted); text-decoration: line-through; }
.sizes .arrow { color: var(--muted); }
.sizes .after { font: 600 22px Consolas, monospace; color: var(--accent); }
.result video { width: 100%; max-height: 260px; background: #000; border-radius: 8px; }
.dl { display: inline-block; padding: 8px 18px; border-radius: 8px; background: var(--accent); color: #1a1205; font-weight: 600; text-decoration: none; font-size: 13px; }
.dl:hover { background: var(--accent-2); }
.path { overflow-wrap: anywhere; }
.foot { overflow-wrap: anywhere; }
</style>
