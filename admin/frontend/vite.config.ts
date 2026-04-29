import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  base: '/admin/',
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist', sourcemap: false },
  server: {
    proxy: {
      '/admin/api': {
        target: 'http://localhost:48082',
        rewrite: (path) => path.replace(/^\/admin/, ''),
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
