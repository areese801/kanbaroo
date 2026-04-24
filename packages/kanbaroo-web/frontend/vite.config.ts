import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/ui/',
  build: {
    outDir: '../src/kanbaroo_web/dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api/v1/events': {
        target: 'ws://localhost:8080',
        ws: true,
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
