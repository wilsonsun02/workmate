import path from 'node:path';

import { defineConfig } from '@vben/vite-config';

import ElementPlus from 'unplugin-element-plus/vite';

export default defineConfig(async () => {
  return {
    application: {},
    vite: {
      plugins: [
        ElementPlus({
          format: 'esm',
        }),
      ],
      resolve: {
        alias: {
          '@': path.resolve(__dirname, 'src'),
        },
      },
      server: {
        host: '0.0.0.0',
        proxy: {
          '/api/admin': {
            changeOrigin: true,
            target: 'http://127.0.0.1:8010',
            ws: true,
          },
        },
      },
    },
  };
});
