import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/landing/',
  build: {
    outDir: '../radar/web/static/landing',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: 'landing.js',
        chunkFileNames: 'chunks/[name].js',
        assetFileNames: (asset) => asset.name?.endsWith('.css') ? 'landing.css' : 'assets/[name][extname]',
      },
    },
  },
});
