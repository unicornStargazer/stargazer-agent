import { fileURLToPath, URL } from 'node:url';

import './node21-crypto-compat.js';
import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';

const webRoot = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root: webRoot,
  plugins: [vue()],
  build: {
    emptyOutDir: true,
    outDir: fileURLToPath(new URL('./dist', import.meta.url)),
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:3000',
    },
  },
});
