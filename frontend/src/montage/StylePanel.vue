<script setup>
import { computed, ref } from 'vue'
import { useMontage } from './store'
import { mapi, errText } from './api'

const m = useMontage()
const songInput = ref(null)
const bumperBusy = ref('')
const advanced = ref(false)

const c = computed(() => m.config)
const P = computed(() => m.presets)
const job = (k) => m.jobs[k]
const running = (k) => job(k) && ['pending', 'running', 'cancelling'].includes(job(k).state)
const pct = (k) => Math.round((job(k)?.progress || 0) * 100)
const selectedCount = computed(() => (m.project?.clips || []).filter(x => x.selected).length)
const desc = (list, id) => (list || []).find(x => x.id === id)?.desc || ''

function num(sec, key, v, { min = -Infinity, max = Infinity, nullable = false } = {}) {
  if (nullable && (v === '' || v == null)) return m.setSetting(sec, key, null)
  const n = Number(v)
  if (Number.isFinite(n)) m.setSetting(sec, key, Math.max(min, Math.min(max, n)))
}
function range(sec, key, i, v) {
  const arr = [...c.value[sec][key]]
  arr[i] = Number(v)
  if (arr.every(Number.isFinite) && arr[0] <= arr[1]) m.setSetting(sec, key, arr)
}
function onSong(e) {
  const f = e.target.files?.[0]
  e.target.value = ''
  if (f) m.uploadSong(f)
}
async function uploadBumper(kind, e) {
  const f = e.target.files?.[0]
  e.target.value = ''
  if (!f) return
  bumperBusy.value = kind
  try {
    const r = await mapi.uploadBumper(kind, f)
    m.presets = await mapi.presets()
    m.setSetting('render', kind === 'intro' ? 'intro_video' : 'outro_video', r.path)
  } catch (err) { m.error = errText(err) } finally { bumperBusy.value = '' }
}
function removeProject() { if (confirm(`删除工程「${m.project.name}」？素材和已出的成片不会删。`)) m.removeProject() }
function rename(v) { if (v.trim()) { m.project.name = v.trim(); m.patch({ name: v.trim() }) } }
</script>

<template>
  <div v-if="c && P" class="sp">
    <section>
      <h3>工程</h3>
      <div class="row2">
        <select :value="m.project.id" @change="m.open($event.target.value)">
          <option v-for="p in m.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button class="ghost tiny" @click="m.newProject()">新建</button>
        <button class="danger tiny" @click="removeProject">删除</button>
      </div>
      <input class="name" :value="m.project.name" placeholder="工程名（也是成片文件名）" @change="rename($event.target.value)" />
    </section>

    <section>
      <h3>① 歌曲</h3>
      <div class="song">
        <div v-if="m.song" class="song-info"><b :title="m.song.name">{{ m.song.name }}</b><span class="muted">{{ m.song.bpm }} BPM · {{ m.song.duration.toFixed(0) }} 秒</span></div>
        <span v-else class="muted">还没选歌（mp3 / flac / wav）</span>
        <button class="tiny" :disabled="running('song')" @click="songInput.click()">{{ m.song ? '换歌' : '选歌' }}</button>
        <input ref="songInput" type="file" accept=".mp3,.flac,.wav,.m4a,.aac,.ogg,.ncm,audio/*" hidden @change="onSong" />
      </div>
      <div v-if="running('song')" class="progress"><i :style="{ width: Math.max(8, pct('song')) + '%' }"></i></div>
      <p v-if="running('song')" class="muted small">{{ job('song').message || '正在分析节拍和重音…' }}</p>
    </section>

    <section>
      <h3>② 风格预设</h3>
      <div class="styles">
        <button v-for="s in P.styles" :key="s.id" class="style" :title="s.desc" @click="m.applyStyle(s)"><b>{{ s.label }}</b><small>{{ s.desc }}</small></button>
      </div>
    </section>

    <section>
      <h3>③ 开头</h3>
      <label class="f">效果
        <select :value="c.render.opening" @change="m.setSetting('render', 'opening', $event.target.value)">
          <option v-for="o in P.openings" :key="o.id" :value="o.id">{{ o.label }}</option>
        </select>
      </label>
      <p class="muted small">{{ desc(P.openings, c.render.opening) }}</p>
      <label class="f">标题<input :value="c.render.title" placeholder="可选，开头 3 秒显示" @change="m.setSetting('render', 'title', $event.target.value)" /></label>
      <label class="f">片头视频
        <select :value="c.render.intro_video || ''" @change="m.setSetting('render', 'intro_video', $event.target.value || null)">
          <option value="">不加</option>
          <option v-for="b in P.bumpers.intro" :key="b.path" :value="b.path">{{ b.name }}（{{ b.duration.toFixed(1) }}s）</option>
        </select>
        <label class="tiny upload" :class="{ busy: bumperBusy === 'intro' }">上传<input type="file" accept="video/*" hidden @change="uploadBumper('intro', $event)" /></label>
      </label>
    </section>

    <section>
      <h3>④ 转场</h3>
      <label class="f">样式
        <select :value="c.plan.transition" @change="m.setSetting('plan', 'transition', $event.target.value)">
          <option v-for="t in P.transitions" :key="t.id" :value="t.id">{{ t.label }}</option>
        </select>
      </label>
      <label class="f">频率
        <select :value="c.plan.transition_every" @change="m.setSetting('plan', 'transition_every', Number($event.target.value))">
          <option :value="0">全部硬切</option>
          <option :value="1">每个切点</option>
          <option :value="2">每 2 个切点</option>
          <option :value="3">每 3 个切点</option>
          <option :value="4">每 4 个切点</option>
        </select>
      </label>
      <p class="muted small">{{ desc(P.transitions, c.plan.transition) }}。单个镜头的转场可以在时间线上单独改。</p>
    </section>

    <section>
      <h3>⑤ 结尾</h3>
      <label class="f">效果
        <select :value="c.render.ending" @change="m.setSetting('render', 'ending', $event.target.value)">
          <option v-for="o in P.endings" :key="o.id" :value="o.id">{{ o.label }}</option>
        </select>
        <input class="n" type="number" step="0.5" min="0.5" max="6" :value="c.render.fade_out" title="结尾效果时长（秒）" @change="num('render', 'fade_out', $event.target.value, { min: 0.5, max: 6 })" />秒
      </label>
      <label class="f">片尾视频
        <select :value="c.render.outro_video || ''" @change="m.setSetting('render', 'outro_video', $event.target.value || null)">
          <option value="">不加</option>
          <option v-for="b in P.bumpers.outro" :key="b.path" :value="b.path">{{ b.name }}（{{ b.duration.toFixed(1) }}s）</option>
        </select>
        <label class="tiny upload" :class="{ busy: bumperBusy === 'outro' }">上传<input type="file" accept="video/*" hidden @change="uploadBumper('outro', $event)" /></label>
      </label>
    </section>

    <section>
      <h3>⑥ 卡点规则 <button class="ghost tiny" @click="advanced = !advanced">{{ advanced ? '收起' : '更多' }}</button></h3>
      <label class="f">成片时长<input class="n" type="number" min="10" max="600" step="5" :value="c.plan.duration" @change="num('plan', 'duration', $event.target.value, { min: 10, max: 600 })" />秒</label>
      <label class="f">每镜头最多<input class="n" type="number" min="1" max="20" :value="c.plan.kills_per_shot ?? ''" placeholder="不限" @change="num('plan', 'kills_per_shot', $event.target.value, { min: 1, max: 20, nullable: true })" />个击杀</label>
      <template v-if="advanced">
        <label class="f">首个镜头前因<input class="n" type="number" step="1" :value="c.plan.first_lead[0]" @change="range('plan', 'first_lead', 0, $event.target.value)" />~<input class="n" type="number" step="1" :value="c.plan.first_lead[1]" @change="range('plan', 'first_lead', 1, $event.target.value)" />秒</label>
        <label class="f">其余镜头前因<input class="n" type="number" step="1" :value="c.plan.lead[0]" @change="range('plan', 'lead', 0, $event.target.value)" />~<input class="n" type="number" step="1" :value="c.plan.lead[1]" @change="range('plan', 'lead', 1, $event.target.value)" />秒</label>
        <label class="f">击杀间最高加速<input class="n" type="number" step="0.05" min="1" max="2" :value="c.plan.speed_max" @change="num('plan', 'speed_max', $event.target.value, { min: 1, max: 2 })" />倍</label>
        <label class="f">快进最高<input class="n" type="number" step="0.5" min="1" max="8" :value="c.plan.ff_speed_max" @change="num('plan', 'ff_speed_max', $event.target.value, { min: 1, max: 8 })" />倍</label>
        <label class="f">同镜头击杀最大间隔<input class="n" type="number" step="1" min="2" :value="c.plan.chain_max_gap ?? ''" placeholder="不限" @change="num('plan', 'chain_max_gap', $event.target.value, { min: 2, nullable: true })" />秒</label>
        <label class="f">游戏声音量<input class="n" type="number" step="0.05" min="0" max="2" :value="c.render.game_volume" @change="num('render', 'game_volume', $event.target.value, { min: 0, max: 2 })" /></label>
        <label class="f">音乐音量<input class="n" type="number" step="0.05" min="0" max="2" :value="c.render.music_volume" @change="num('render', 'music_volume', $event.target.value, { min: 0, max: 2 })" /></label>
        <label class="f chk"><input type="checkbox" :checked="c.render.hq" @change="m.setSetting('render', 'hq', $event.target.checked)" />变速段补帧（画面更顺，出片慢约 10 倍）</label>
      </template>
    </section>

    <section class="actions">
      <button class="primary" :disabled="m.busy || !m.song || !selectedCount" :title="!m.song ? '先选歌' : !selectedCount ? '先在左边勾选素材' : ''" @click="m.autoPlan()">
        {{ running('plan') ? '正在编排…' : m.shots.length ? '重新自动编排' : '自动编排' }}
      </button>
      <p v-if="running('plan')" class="muted small">{{ job('plan').message }}</p>
      <p v-if="m.project.skipped?.length" class="muted small">跳过：{{ m.project.skipped.join('；') }}</p>
      <button :disabled="m.busy || !m.shots.length" @click="m.render()">{{ running('render') ? `出片中 ${pct('render')}%` : '出片' }}</button>
      <template v-if="running('render')">
        <div class="progress"><i :style="{ width: Math.max(4, pct('render')) + '%' }"></i></div>
        <p class="muted small">{{ job('render').message }} <button class="ghost tiny" @click="m.cancelRender()">取消</button></p>
      </template>
      <ul v-if="m.project.renders?.length" class="renders">
        <li v-for="r in m.project.renders.slice(0, 5)" :key="r.path">
          <a :href="mapi.fileUrl(r.path)" target="_blank" :title="r.path">{{ r.name }}</a><span class="muted">{{ r.duration.toFixed(1) }}s</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.sp { display: flex; flex-direction: column; gap: 4px; }
section { padding: 8px 0 10px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; }
section:last-child { border-bottom: 0; }
h3 { margin: 0; font-size: 12px; color: var(--accent-2); display: flex; align-items: center; justify-content: space-between; }
.row2 { display: flex; gap: 6px; } .row2 select { flex: 1; min-width: 0; padding: 5px; font-size: 12px; }
.name { font-size: 12px; padding: 5px 7px; }
.tiny { padding: 3px 8px; font-size: 11px; }
.song { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.song-info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.song-info b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.song-info span { font-size: 11px; }
.song > .muted { flex: 1; }
.styles { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.style { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; padding: 6px 8px; text-align: left; }
.style b { font-size: 12px; } .style small { font-size: 10px; color: var(--muted); line-height: 1.4; }
.f { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #b6bfca; }
.f select { flex: 1; min-width: 0; padding: 4px 6px; font-size: 12px; }
.f > input:not(.n):not([type=checkbox]) { flex: 1; min-width: 0; padding: 4px 7px; font-size: 12px; }
.n { width: 58px; padding: 4px 5px; font-size: 12px; }
.chk input { accent-color: var(--accent); }
.small { margin: 0; font-size: 11px; line-height: 1.6; }
.upload { border: 1px solid var(--border); border-radius: 6px; cursor: pointer; white-space: nowrap; color: var(--text); }
.upload.busy { opacity: .5; pointer-events: none; }
.actions button:not(.tiny) { width: 100%; }
.renders { margin: 4px 0 0; padding: 0; list-style: none; font-size: 11px; display: flex; flex-direction: column; gap: 3px; }
.renders li { display: flex; gap: 6px; justify-content: space-between; } .renders a { color: #9ad1ff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
