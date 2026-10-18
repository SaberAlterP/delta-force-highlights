import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    // video.js 及其流媒体解析依赖约 691 kB；独立缓存后业务包仅约 43 kB。
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks: {
          'video-player': ['video.js'],
          'vue-runtime': ['vue', 'pinia'],
          'http-client': ['axios'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 把 /api 代理到后端，前端代码里直接用相对路径
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
