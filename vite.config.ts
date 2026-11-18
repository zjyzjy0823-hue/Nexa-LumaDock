import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '^/api/.+': 'http://127.0.0.1:8000',
      '/ws': { target: 'http://127.0.0.1:8000', ws: true },
    },
  },
})
