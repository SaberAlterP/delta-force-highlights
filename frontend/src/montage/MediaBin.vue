<script setup>
import { computed, ref } from 'vue'
import { useMontage } from './store'
import { mapi, errText } from './api'
import { api } from '../api'

const m = useMontage()
const filter = ref('all')
const query = ref('')
const pathInput = ref('')
const editingPath = ref(false)

const KIND = { highlight: '高光', original: '整局', manual: '手动剪辑', other: '视频' }
const killsOf = (it) => {
  const c = m.clipMap[it.path]
  return c?.manual_kills?.length ? { n: c.manual_kills.length, manual: true } : { n: it.auto_kills, manual: false }
}
const isOn = (it) => !!m.clipMap[it.path]?.selected
const items = computed(() => {
  const q = query.value.trim().toLowerCase()
  return (m.scan?.items || []).filter(it =>
    (filter.value === 'all' || (filter.value === 'on' ? isOn(it) : filter.value === 'kills' ? killsOf(it).n > 0 : it.kind === filter.value))
    && (!q || it.rel.toLowerCase().includes(q)))
})
const groups = computed(() => {
  const out = new Map()
  for (const it of items.value) {
    if (!out.has(it.group)) out.set(it.group, [])
    out.get(it.group).push(it)
  }
  return [...out.entries()]
})
const selectedCount = computed(() => (m.project?.clips || []).filter(c => c.selected).length)
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, '0')}`

async function pick() {
  try {
    const p = await api.pickFolder(m.project?.folder || '', '选择素材文件夹')
    if (p) m.setFolder(p)
  } catch (e) { m.error = errText(e, '无法打开选择窗口，可以直接输入路径') ; editingPath.value = true }
}
async function useDefault() {
  const p = await mapi.defaultFolder()
  if (p) m.setFolder(p); else m.error = '还没在设置里填集锦文件夹'
}
function submitPath() { editingPath.value = false; m.setFolder(pathInput.value.trim()) }
function selectAll(on) { for (const it of items.value) if (isOn(it) !== on && (!on || killsOf(it).n > 0)) m.toggleClip(it, on) }
</script>

<template>
  <aside class="panel bin">
    <header>
      <b>素材</b>
      <span class="muted count">已选 {{ selectedCount }}</span>
      <span class="spacer"></span>
      <button class="ghost tiny" :disabled="m.scanning" title="重新读取文件夹" @click="m.rescan()">⟳</button>
    </header>
    <div class="folder">
      <template v-if="!editingPath">
        <span class="path" :title="m.project?.folder"><bdi>{{ m.project?.folder || '还没选文件夹' }}</bdi></span>
        <button class="tiny" @click="pick">选择文件夹</button>
      </template>
      <form v-else class="path-edit" @submit.prevent="submitPath">
        <input v-model="pathInput" placeholder="粘贴文件夹路径，回车" autofocus />
      </form>
    </div>
    <div class="quick">
      <button class="ghost tiny" @click="useDefault">集锦文件夹</button>
      <button class="ghost tiny" @click="pathInput = m.project?.folder || ''; editingPath = !editingPath">输入路径</button>
    </div>
    <div class="filters">
      <select v-model="filter">
        <option value="all">全部视频</option>
        <option value="kills">有击杀的</option>
        <option value="highlight">自动高光</option>
        <option value="original">整局原片</option>
        <option value="on">已选</option>
      </select>
      <input v-model="query" placeholder="搜索文件名" />
    </div>
    <div class="bulk">
      <button class="ghost tiny" @click="selectAll(true)">全选有击杀的</button>
      <button class="ghost tiny" @click="selectAll(false)">全不选</button>
    </div>

    <div class="list scroll">
      <p v-if="m.scanning" class="muted empty">正在读取文件夹…</p>
      <p v-else-if="!items.length" class="muted empty">{{ m.scan ? '这里没有符合条件的视频' : '选一个放素材的文件夹。集锦文件夹里的高光会自动带上击杀时间。' }}</p>
      <section v-for="[g, list] in groups" :key="g">
        <h4 v-if="g !== '.'">{{ g }}</h4>
        <div v-for="it in list" :key="it.path" class="item" :class="{ on: isOn(it), active: m.source === it.path }" @click="m.source = it.path">
          <label class="chk" @click.stop><input type="checkbox" :checked="isOn(it)" @change="m.toggleClip(it, $event.target.checked)" /></label>
          <img :src="mapi.thumbUrl(it.path, Math.min(3, it.duration / 2))" loading="lazy" alt="" />
          <div class="meta">
            <span class="name" :title="it.rel">{{ it.name }}</span>
            <span class="sub">
              <em>{{ KIND[it.kind] }}</em> {{ fmt(it.duration) }}
              <b v-if="killsOf(it).n" :class="{ manual: killsOf(it).manual }">{{ killsOf(it).n }} 杀{{ killsOf(it).manual ? '（手标）' : '' }}</b>
              <i v-else>无击杀</i>
            </span>
          </div>
        </div>
      </section>
      <p v-if="m.scan?.truncated" class="muted empty">文件太多，只显示了前 600 个</p>
    </div>
  </aside>
</template>

<style scoped>
.bin { display: flex; flex-direction: column; gap: 8px; padding: 10px; min-height: 0; }
header { display: flex; align-items: center; gap: 8px; }
.count { font-size: 11px; }
.folder { display: flex; align-items: center; gap: 6px; }
.path { flex: 1; min-width: 0; font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: rtl; text-align: left; }
.path-edit { flex: 1; } .path-edit input { width: 100%; font-size: 12px; padding: 5px 7px; }
.quick, .bulk { display: flex; gap: 6px; }
.filters { display: flex; gap: 6px; } .filters select { width: 104px; padding: 5px; font-size: 12px; } .filters input { flex: 1; min-width: 0; padding: 5px 7px; font-size: 12px; }
.tiny { padding: 3px 8px; font-size: 11px; }
.list { flex: 1; min-height: 0; margin: 0 -4px; padding: 0 4px; }
.empty { font-size: 12px; line-height: 1.7; padding: 8px 2px; }
h4 { margin: 10px 0 4px; font-size: 11px; color: var(--muted); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.item { display: flex; align-items: center; gap: 7px; padding: 5px; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.item:hover { background: var(--panel-2); }
.item.active { border-color: #4aa3ff; }
.item.on { background: #2a2213; }
.chk { display: flex; padding: 4px; cursor: pointer; } .chk input { accent-color: var(--accent); }
img { width: 72px; height: 40px; object-fit: cover; border-radius: 4px; background: #000; flex: none; }
.meta { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
.name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 10px; color: var(--muted); }
.sub em { font-style: normal; padding: 0 4px; border: 1px solid var(--border); border-radius: 3px; margin-right: 3px; }
.sub b { color: #ff8a80; font-weight: 600; margin-left: 4px; } .sub b.manual { color: #9ad1ff; }
.sub i { font-style: normal; margin-left: 4px; opacity: .7; }
</style>
