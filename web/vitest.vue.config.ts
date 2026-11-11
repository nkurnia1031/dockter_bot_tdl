import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [vue()],
  resolve: { conditions: ['browser'] },
  test: {
    environment: 'jsdom',
    include: ['vue/src/**/*.test.ts'],
    setupFiles: ['./vue/src/test-setup.ts']
  }
});
