import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Served by the shared plugin host at /api/v1/plugins/ideation/ui/* (the API
// Gateway path, not a separate CloudFront/S3 origin) — every asset/link URL
// must carry that full prefix. See web-admin/vite.config.ts for what happens
// when it doesn't: a missing segment 404s at the host and CloudFront's
// 404->index.html custom error response papers over it as a 200 serving the
// portal's homepage, so the browser tries to parse HTML as JS.
export default defineConfig({
  base: '/api/v1/plugins/ideation/ui/',
  plugins: [react()],
  // amazon-cognito-identity-js's `buffer` dependency references Node's `global`,
  // which Vite (unlike webpack/CRA) does not polyfill — without this the app
  // crashes on load with "ReferenceError: global is not defined" in any browser.
  define: { global: 'globalThis' },
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
