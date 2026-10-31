<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useMontage } from './store'
import { mapi, errText } from './api'

const m = useMontage()
const text = ref('')
const busy = ref(false)
const err = ref('')
const listEl = ref(null)
const keyInput = ref('')
const modelInput = ref('')
const showSetup = ref(false)

const chat = computed(() => m.project?.chat || [])
const needKey = computed(() => !m.settings?.api_key_set)
const IDEAS = [
  '按这首歌剪一版 45 秒的，最多杀的那段放在最重的重音上',
  '开头加个标题「周末上分」，转场换成甩镜',
  '第 2 个镜头前因太长了，缩短一点',
  '检查一下时间线，有没有击杀没卡在拍上的',
]

async function send(t = text.value) {
  t = t.trim()
  if (!t || busy.value) return
  busy.value = true; err.value = ''
  m.project.chat = [...chat.value, { role: 'user', text: t, pending: true }]
  text.value = ''
  try { m.project = await mapi.agent(m.project.id, t) }
  catch (e) {
    err.value = errText(e, '助手没有回应')
    m.project.chat = chat.value.filter(x => !x.pending)
    text.value = t
    if (e?.response?.status === 401) showSetup.value = true
  } finally { busy.value = false }
}
async function saveSetup() {
  try {
    await m.saveAgentSettings({ api_key: keyInput.value || undefined, model: modelInput.value || undefined })
    keyInput.value = ''; showSetup.value = false; err.value = ''
  } catch (e) { err.value = errText(e) }
}
async function reset() { if (confirm('清空和助手的对话？时间线不受影响。')) m.project = await mapi.agentReset(m.project.id) }
function onEnter(e) { if (!e.shiftKey && !e.isComposing) { e.preventDefault(); send() } }

watch(() => chat.value.length, () => nextTick(() => { if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight }))
</script>

<template>
  <div class="ap">
    <div v-if="needKey || showSetup" class="setup">
      <p>助手用 Claude 帮你挑素材、改参数、调时间线。只发送文件名、击杀时间、节拍和参数，<b>不上传视频和音频</b>。</p>
      <input v-model="keyInput" type="password" :placeholder="m.settings?.api_key_set ? '已填写，留空不改' : 'Claude API Key（sk-ant-…）'" autocomplete="off" />
      <input v-model="modelInput" :placeholder="`模型（默认 ${m.settings?.model || 'claude-opus-5-5'}）`" />
      <div class="row2">
        <button class="primary tiny" :disabled="!keyInput && !modelInput" @click="saveSetup">保存</button>
        <button v-if="!needKey" class="ghost tiny" @click="showSetup = false">取消</button>
      </div>
      <p class="muted small">Key 只保存在本机 backend/storage/montage/settings.json，也可以用环境变量 ANTHROPIC_API_KEY。</p>
    </div>

    <div ref="listEl" class="list scroll">
      <div v-if="!chat.length" class="intro">
        <p class="muted">告诉助手你想要什么样的成片，它会改参数、自动编排，再按你的意见微调。改完的时间线随时可以自己拖。</p>
        <button v-for="i in IDEAS" :key="i" class="ghost idea" :disabled="needKey || busy" @click="send(i)">{{ i }}</button>
      </div>
      <div v-for="(msg, i) in chat" :key="i" class="msg" :class="msg.role">
        <div class="bubble">{{ msg.text || (msg.role === 'assistant' ? '（完成）' : '') }}</div>
        <ul v-if="msg.changes?.length" class="changes"><li v-for="c in msg.changes" :key="c">✓ {{ c }}</li></ul>
      </div>
      <div v-if="busy" class="msg assistant"><div class="bubble thinking">思考中<i>.</i><i>.</i><i>.</i></div></div>
    </div>

    <p v-if="err" class="err">{{ err }}</p>
    <div class="input">
      <textarea v-model="text" rows="2" :disabled="needKey" placeholder="比如：把最后一个镜头换成甩镜，结尾留长一点（Enter 发送，Shift+Enter 换行）" @keydown.enter="onEnter"></textarea>
      <div class="row2">
        <button class="ghost tiny" :disabled="!chat.length || busy" @click="reset">清空对话</button>
        <button class="ghost tiny" @click="showSetup = !showSetup">设置</button>
        <span class="spacer"></span>
        <button class="primary tiny" :disabled="needKey || busy || !text.trim()" @click="send()">发送</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ap { display: flex; flex-direction: column; gap: 8px; height: 100%; min-height: 0; }
.setup { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid #5d4820; background: #2a2213; border-radius: 8px; font-size: 12px; }
.setup p { margin: 0; line-height: 1.6; }
.setup input { font-size: 12px; padding: 5px 7px; }
.row2 { display: flex; gap: 6px; align-items: center; }
.tiny { padding: 4px 10px; font-size: 11px; }
.small { font-size: 11px; }
.list { flex: 1; min-height: 160px; display: flex; flex-direction: column; gap: 8px; }
.intro { display: flex; flex-direction: column; gap: 6px; font-size: 12px; line-height: 1.6; }
.intro p { margin: 0 0 4px; }
.idea { text-align: left; font-size: 12px; padding: 6px 9px; }
.msg { display: flex; flex-direction: column; gap: 3px; }
.msg.user { align-items: flex-end; }
.bubble { max-width: 92%; padding: 7px 10px; border-radius: 9px; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.user .bubble { background: #3a2d12; border: 1px solid #5d4820; }
.assistant .bubble { background: var(--panel-2); border: 1px solid var(--border); }
.changes { margin: 0; padding: 0 0 0 4px; list-style: none; font-size: 11px; color: var(--ok); }
.thinking i { animation: blink 1.2s infinite; font-style: normal; } .thinking i:nth-child(2) { animation-delay: .2s; } .thinking i:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 50% { opacity: .2; } }
.err { margin: 0; font-size: 11px; color: #f0a6a8; }
.input { display: flex; flex-direction: column; gap: 6px; }
textarea { resize: vertical; font: inherit; font-size: 12px; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; }
textarea:focus { outline: none; border-color: var(--accent); }
</style>
