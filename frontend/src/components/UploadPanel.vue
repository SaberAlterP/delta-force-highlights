<script setup>
import { ref } from 'vue'
import { useStore } from '../store'
import { fmtSize, fmtTime } from '../util'

const store = useStore()
const fileInput = ref(null)
const dragOver = ref(false)

function pick() { fileInput.value?.click() }

async function handleFiles(files) {
  const file = files?.[0]
  if (!file) return
  if (!/\.(mp4|mov|mkv|avi)$/i.test(file.name)) {
    alert('请上传 MP4 等视频文件')
    return
  }
  await store.uploadFile(file).catch(() => {})
}

function onChange(e) { handleFiles(e.target.files); e.target.value = '' }
function onDrop(e) { dragOver.value = false; handleFiles(e.dataTransfer.files) }

function confirmRemove(v) {
  if (window.confirm(`从视频库移除「${v.filename}」？\n（仅移除列表与其击杀标记；服务器视频文件可在「缓存管理」里清理）`)) {
    store.removeFromLibrary(v.upload_id)
  }
}
</script>

<template>
  <div class="panel">
    <h2>上传录像</h2>

    <div
      class="dropzone"
      :class="{ over: dragOver, busy: store.upload.busy }"
      @click="pick"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <input ref="fileInput" type="file" accept="video/*" hidden @change="onChange" />
      <template v-if="!store.upload.busy">
        <div class="dz-icon">⬆️</div>
        <div>点击或拖拽视频到此处</div>
        <div class="muted small">支持 MP4 / MOV / MKV，可上传多个</div>
      </template>
      <template v-else>
        <div class="muted">上传中… {{ store.upload.progress }}%</div>
        <div class="progress" style="width:100%;margin-top:8px">
          <i :style="{ width: store.upload.progress + '%' }"></i>
        </div>
      </template>
    </div>

    <p v-if="store.upload.error" class="err">{{ store.upload.error }}</p>

    <!-- 视频库：点击切换当前剪辑的视频 -->
    <div v-if="store.library.length" class="library">
      <div class="lib-title muted">视频库（{{ store.library.length }}）· 点击切换当前视频</div>
      <div class="lib-list scroll">
        <div
          v-for="v in store.library"
          :key="v.upload_id"
          class="lib-item"
          :class="{ active: store.video?.upload_id === v.upload_id }"
          @click="store.selectVideo(v.upload_id)"
        >
          <div class="li-row">
            <span class="li-dot"></span>
            <span class="li-name" :title="v.filename">{{ v.filename }}</span>
            <button class="li-del" title="从库移除" @click.stop="confirmRemove(v)">✕</button>
          </div>
          <div class="li-meta muted">
            {{ fmtTime(v.duration) }} · {{ v.width }}×{{ v.height }} · {{ fmtSize(v.size_bytes) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dropzone {
  border: 1.5px dashed var(--border);
  border-radius: var(--radius);
  padding: 22px 14px;
  text-align: center;
  transition: border-color .15s, background .15s;
}
.dropzone:hover, .dropzone.over { border-color: var(--accent); background: #1a212b; }
.dropzone.busy { cursor: default; }
.dz-icon { font-size: 28px; margin-bottom: 6px; }
.small { font-size: 12px; margin-top: 4px; }
.err { color: var(--danger); font-size: 12px; margin: 10px 0 0; }

.library { margin-top: 14px; }
.lib-title { font-size: 12px; margin-bottom: 8px; }
.lib-list { display: flex; flex-direction: column; gap: 6px; max-height: 220px; }
.lib-item {
  padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--panel-2); cursor: pointer; transition: border-color .15s, background .15s;
}
.lib-item:hover { border-color: var(--accent); }
.lib-item.active { border-color: var(--accent); background: #2a2212; }
.li-row { display: flex; align-items: center; gap: 8px; }
.li-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--border); flex: none;
}
.lib-item.active .li-dot { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
.li-name {
  flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.li-del {
  border: none; background: transparent; color: var(--muted); padding: 2px 6px;
  border-radius: 6px; font-size: 12px;
}
.li-del:hover { color: var(--danger); background: #2a1718; }
.li-meta { font-size: 11px; margin-top: 4px; padding-left: 16px; }
</style>
