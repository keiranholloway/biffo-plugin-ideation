import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Served path-routed at <base>/ideation/* on the shared CloudFront (ADR-0018),
// so every asset/link URL must carry the /ideation/ prefix. The parent CDN
// forwards the full path to this app's S3 origin with no prefix stripping.
export default defineConfig({
  base: '/ideation/',
  plugins: [react()],
  // amazon-cognito-identity-js's `buffer` dependency references Node's `global`,
  // which Vite (unlike webpack/CRA) does not polyfill — without this the app
  // crashes on load with "ReferenceError: global is not defined" in any browser.
  define: { global: 'globalThis' },
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
