<script setup>
defineProps({ show: Boolean, label: { type: String, default: '正在加载画面…' }, progress: { type: Number, default: null } })
</script>

<template>
  <Transition name="veil">
    <div v-if="show" class="veil" role="status" aria-live="polite">
      <div class="ring"><i></i><i></i><i></i></div>
      <span class="label">{{ label }}</span>
      <span v-if="progress != null" class="bar"><b :style="{ width: Math.round(progress * 100) + '%' }"></b></span>
    </div>
  </Transition>
</template>

<style scoped>
.veil { position: absolute; inset: 0; z-index: 3; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px;
  background: radial-gradient(ellipse at center, rgba(14,17,22,.55), rgba(14,17,22,.82)); backdrop-filter: blur(2px); pointer-events: none; }
.ring { position: relative; width: 54px; height: 54px; }
.ring i { position: absolute; inset: 0; border: 3px solid transparent; border-top-color: var(--accent); border-radius: 50%; animation: spin 1.1s cubic-bezier(.5, .1, .5, .9) infinite; }
.ring i:nth-child(2) { inset: 8px; border-top-color: var(--accent-2); animation-duration: 1.5s; animation-direction: reverse; opacity: .8; }
.ring i:nth-child(3) { inset: 17px; border-top-color: #fff; animation-duration: .9s; opacity: .5; }
.label { font-size: 13px; color: #e6e9ee; letter-spacing: .5px; text-shadow: 0 1px 4px #000; }
.bar { width: 140px; height: 3px; background: rgba(255,255,255,.15); border-radius: 3px; overflow: hidden; }
.bar b { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .3s; }
@keyframes spin { to { transform: rotate(360deg); } }
.veil-enter-active, .veil-leave-active { transition: opacity .25s; }
.veil-enter-from, .veil-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .ring i { animation-duration: 3s; } }
</style>
