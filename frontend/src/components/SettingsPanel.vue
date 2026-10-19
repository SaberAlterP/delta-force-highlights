<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { useStore } from '../store'

const store = useStore()
const draft = ref(null)
const env = ref(null)
const autostart = ref(null)
const autoBusy = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')

const MODES = [
  { value: 'idle', title: '打完游戏再处理（推荐）', desc: '检测到正在玩游戏就暂停；识别途中开始玩，会中断并在玩完后重新开始，不抢显卡。' },
  { value: 'auto', title: '录完马上处理', desc: '不管在不在玩，新录像写完就开始识别。' },
  { value: 'manual', title: '只在我点开始时处理', desc: '新录像只登记到列表，在网页里点「开始处理」或「全部开始处理」。' },
]
const KEYS = ['enabled', 'player_id', 'watch_root', 'output_root', 'window_seconds', 'min_operators', 'pre_seconds',
  'post_seconds', 'retention_days', 'delete_after_retention', 'stretch_169', 'use_gpu', 'prefer_official_events',
  'wegame_db_dir', 'notify_on_complete', 'auto_clean_cache', 'process_mode', 'pause_on_fullscreen',
  'extra_game_processes', 'idle_wait_minutes']

function load() {
  const s = store.workflow?.settings
  if (s) draft.value = Object.fromEntries(KEYS.map(k => [k, s[k]]))
}
async function loadEnv() {
  try { env.value = await api.workflowEnvironment() } catch { env.value = null }
}
async function loadAutostart() {
  try { autostart.value = await api.autostartStatus() } catch { autostart.value = null }
}
// 开机自启直接改系统的启动文件夹，点了立即生效，不经过「保存设置」
async function toggleAutostart(enabled) {
  autoBusy.value = true; error.value = ''
  try {
    autostart.value = await api.setAutostart(enabled)
    notice.value = enabled ? '已开启：以后登录 Windows 会在后台自动启动' : '已关闭开机自动启动'
  } catch (e) { error.value = e?.response?.data?.detail || '修改开机启动失败' }
  finally { autoBusy.value = false }
}
onMounted(async () => { if (!store.workflow) await store.refreshWorkflow(); load(); loadEnv(); loadAutostart() })

const dirty = computed(() => draft.value && store.workflow && KEYS.some(k => draft.value[k] !== store.workflow.settings[k]))
const missing = computed(() => draft.value ? [
  !draft.value.player_id?.trim() && '游戏 ID', !draft.value.watch_root && '录像文件夹', !draft.value.output_root && '集锦文件夹',
].filter(Boolean) : [])

async function pick(key, title) {
  error.value = ''
  try {
    const path = await api.pickFolder(draft.value[key], title)
    if (path) draft.value[key] = path
  } catch (e) { error.value = e?.response?.data?.detail || '无法打开文件夹选择窗口，可以直接粘贴路径' }
}

async function save() {
  saving.value = true; error.value = ''; notice.value = ''
  try {
    const values = { ...draft.value }
    if (missing.value.length) values.enabled = false
    await store.saveWorkflowSettings(values)
    load(); await loadEnv()
    notice.value = missing.value.length ? `已保存。还差：${missing.value.join('、')}，填好后才能开启自动监控。` : '已保存'
  } catch (e) { error.value = e?.response?.data?.detail || e.message || '保存失败' }
  finally { saving.value = false }
}

async function testNotify() {
  try {
    const r = await api.workflowNotificationTest()
    notice.value = r.sent ? '测试通知已发出，看看屏幕右下角。' : `通知没有发出：${r.error}`
  } catch (e) { error.value = e.message }
}
async function cleanCache() {
  try {
    const r = await api.workflowCleanupCache()
    notice.value = `清理了 ${r.removed_files} 个到期缓存文件，释放 ${(r.removed_bytes / 1048576).toFixed(1)} MB。`
  } catch (e) { error.value = e.message }
}
</script>

<template>
  <div v-if="draft" class="settings">
    <section>
      <h3>基本设置 <small>必填</small></h3>
      <label class="field">
        <span>你的游戏 ID</span>
        <input v-model.trim="draft.player_id" placeholder="击杀信息里显示的名字" />
        <em>用来在右上角击杀信息里认出你自己的击杀。</em>
      </label>
      <label class="field">
        <span>录像文件夹</span>
        <div class="pick"><input v-model.trim="draft.watch_root" placeholder="例如 E:\record" /><button class="ghost" type="button" @click="pick('watch_root', '选择游戏录像保存的文件夹')">选择…</button></div>
        <em>填 WeGame「精彩时刻」设置里的录像导出文件夹。
          <b v-if="env?.watch_root.path" :class="env.watch_root.exists ? 'ok' : 'bad'">{{ env.watch_root.exists ? '✓ 文件夹存在' : '✗ 找不到这个文件夹' }}</b></em>
      </label>
      <label class="field">
        <span>集锦文件夹</span>
        <div class="pick"><input v-model.trim="draft.output_root" placeholder="例如 D:\集锦" /><button class="ghost" type="button" @click="pick('output_root', '选择保存集锦的文件夹')">选择…</button></div>
        <em>每局一个子文件夹，放整局原片、高光和说明。改了以后只影响之后的新对局，已有的不会搬走。</em>
      </label>
      <label class="check"><input type="checkbox" v-model="draft.enabled" :disabled="missing.length > 0" />
        <span>自动监控新录像<em v-if="missing.length">（先填好：{{ missing.join('、') }}）</em></span></label>
      <label v-if="autostart?.supported" class="check"><input type="checkbox" :checked="autostart.enabled" :disabled="autoBusy" @change="toggleAutostart($event.target.checked)" />
        <span>开机自动启动<em>登录 Windows 后在后台静默运行（不弹窗口、不开浏览器，待机约 50MB 内存）。点了立即生效。</em></span></label>
    </section>

    <section>
      <h3>什么时候处理新录像</h3>
      <div class="modes" role="radiogroup">
        <label v-for="m in MODES" :key="m.value" class="mode" :class="{ on: draft.process_mode === m.value }">
          <input type="radio" :value="m.value" v-model="draft.process_mode" />
          <span><b>{{ m.title }}</b><em>{{ m.desc }}</em></span>
        </label>
      </div>
      <template v-if="draft.process_mode === 'idle'">
        <label class="field inline"><span>游戏关掉后再等</span><input type="number" min="0" max="120" v-model.number="draft.idle_wait_minutes" /><span>分钟</span></label>
        <label class="check"><input type="checkbox" v-model="draft.pause_on_fullscreen" />
          <span>任何全屏程序都算在玩<em>（不在名单里的游戏也能识别；浏览器、播放器全屏看视频不算）</em></span></label>
        <label class="field">
          <span>额外的游戏进程名</span>
          <input v-model.trim="draft.extra_game_processes" placeholder="例如 MyGame.exe, OtherGame.exe" />
          <em>已内置三角洲行动和常见游戏。窗口化玩的游戏如果没被识别，在任务管理器「详细信息」里找到它的进程名填进来。</em>
        </label>
        <p v-if="store.workflow?.paused" class="hint now">现在：{{ store.workflow.paused }}</p>
      </template>
    </section>

    <section>
      <h3>集锦规则</h3>
      <div class="grid">
        <label class="field"><span>时间窗（秒）</span><input type="number" min="1" max="600" v-model.number="draft.window_seconds" /></label>
        <label class="field"><span>至少几杀</span><input type="number" min="2" max="20" v-model.number="draft.min_operators" /></label>
        <label class="field"><span>片段前留（秒）</span><input type="number" min="0" max="300" v-model.number="draft.pre_seconds" /></label>
        <label class="field"><span>片段后留（秒）</span><input type="number" min="0" max="300" v-model.number="draft.post_seconds" /></label>
      </div>
      <p class="hint">现在：{{ draft.window_seconds }} 秒内击杀 {{ draft.min_operators }} 名及以上不同干员就剪一段，前留 {{ draft.pre_seconds }} 秒、后留 {{ draft.post_seconds }} 秒。</p>
      <label class="check"><input type="checkbox" v-model="draft.stretch_169" /><span>集锦拉伸成 16:9<em>（4:3 拉伸玩法录的画面导出时铺满宽屏，原片不受影响）</em></span></label>
    </section>

    <section>
      <h3>原片保留</h3>
      <label class="check"><input type="checkbox" v-model="draft.delete_after_retention" /><span>到期自动删除整局原片<em>（高光一直保留；校验不通过时不会删）</em></span></label>
      <label v-if="draft.delete_after_retention" class="field inline"><span>保留天数</span><input type="number" min="1" max="365" v-model.number="draft.retention_days" /></label>
    </section>

    <section>
      <h3>识别</h3>
      <label class="check"><input type="checkbox" v-model="draft.use_gpu" />
        <span>使用显卡（GPU）加速识别
          <em v-if="env">{{ env.gpu ? '✓ 检测到可用的 NVIDIA 显卡' : '✗ 没检测到可用的 CUDA 显卡，会自动改用 CPU（慢一些）' }}</em></span></label>
      <label class="check"><input type="checkbox" v-model="draft.prefer_official_events" />
        <span>优先使用游戏官方标注点<em>（直接读取游戏录像工具记下的击杀时间，更快更准；找不到时再看画面识别）</em></span></label>
      <label v-if="draft.prefer_official_events" class="field">
        <span>官方标注点数据目录</span>
        <div class="pick"><input v-model.trim="draft.wegame_db_dir" placeholder="留空 = 自动查找" /><button class="ghost" type="button" @click="pick('wegame_db_dir', '选择 wonderfulDb 文件夹')">选择…</button></div>
        <em v-if="env">
          <b :class="env.wegame.exists && env.wegame.accounts ? 'ok' : 'bad'">{{ env.wegame.exists ? (env.wegame.accounts ? `✓ 找到 ${env.wegame.accounts} 个账号的标注数据` : '✗ 目录在，但里面没有标注数据') : '✗ 没找到标注数据目录' }}</b>
          <b :class="env.wegame.node ? 'ok' : 'bad'">{{ env.wegame.node ? '✓ 已安装 Node.js' : '✗ 需要安装 Node.js 才能读取' }}</b>
          <br>当前：{{ env.wegame.path }} · 怎么找见使用指南第 2 步
        </em>
      </label>
    </section>

    <section>
      <h3>其他</h3>
      <label class="check"><input type="checkbox" v-model="draft.notify_on_complete" /><span>处理完发 Windows 通知</span></label>
      <label class="check"><input type="checkbox" v-model="draft.auto_clean_cache" /><span>自动清理到期缓存<em>（手动上传的录像七天没用就清掉）</em></span></label>
      <div class="row"><button class="ghost" type="button" @click="testNotify">发一条测试通知</button><button class="ghost" type="button" @click="cleanCache">现在清理缓存</button></div>
    </section>

    <div class="save">
      <p v-if="error" class="msg bad" role="alert">{{ error }}</p>
      <p v-else-if="notice" class="msg ok" role="status">{{ notice }}</p>
      <button class="primary" :disabled="saving || !dirty" @click="save">{{ saving ? '保存中…' : dirty ? '保存设置' : '已保存' }}</button>
    </div>
  </div>
  <p v-else class="hint">正在读取设置…</p>
</template>

<style scoped>
.settings { display: flex; flex-direction: column; gap: 6px; }
section { padding: 14px 0; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 12px; }
h3 { margin: 0; font-size: 14px; } h3 small { font-weight: 400; color: var(--accent); font-size: 11px; margin-left: 6px; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.field.inline { flex-direction: row; align-items: center; } .field.inline input { width: 90px; }
.field em, .check em { font-style: normal; font-size: 11px; color: var(--muted); line-height: 1.7; }
.check em { display: block; }
em b { font-weight: 400; margin-right: 10px; } .ok { color: var(--ok); } .bad { color: var(--danger); }
.pick { display: flex; gap: 6px; } .pick input { flex: 1; min-width: 0; } .pick button { flex: none; padding: 7px 12px; }
.modes { display: flex; flex-direction: column; gap: 6px; }
.mode { display: flex; gap: 10px; align-items: flex-start; padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
.mode.on { border-color: var(--accent); background: #f5a6230a; }
.mode input { margin-top: 3px; accent-color: var(--accent); }
.mode b { display: block; font-size: 13px; font-weight: 600; } .mode em { font-style: normal; font-size: 11px; color: var(--muted); line-height: 1.6; }
.field.inline span:last-child { color: var(--muted); }
.now { color: var(--accent); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .grid input { width: 100%; }
.check { display: flex; gap: 9px; align-items: flex-start; font-size: 13px; line-height: 1.5; cursor: pointer; }
.check input { margin-top: 3px; accent-color: var(--accent); }
.hint { margin: 0; font-size: 11px; color: var(--muted); line-height: 1.7; }
.row { display: flex; gap: 8px; flex-wrap: wrap; } .row button { font-size: 12px; padding: 6px 12px; }
.save { position: sticky; bottom: 0; background: var(--panel); padding: 14px 0 18px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; }
.save button { width: 100%; }
.msg { margin: 0; font-size: 12px; line-height: 1.6; } .msg.ok { color: var(--ok); } .msg.bad { color: var(--danger); }
</style>
