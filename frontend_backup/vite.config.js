import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    watch: {
      usePolling: true,  // Docker内でのファイル変更検知に必須
    },
  },
  optimizeDeps: {
    exclude: ['onnxruntime-web'],  // WASM動的importをViteのバンドルから除外
  },
})
