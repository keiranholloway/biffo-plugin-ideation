import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Served path-routed at <base>/ideation/admin/* on the shared plugin host,
// so every asset/link URL must carry the /ideation/admin/ prefix.
export default defineConfig({
  base: '/ideation/admin/',
  plugins: [react()],
  build: { outDir: 'dist' },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test-setup.ts'] },
})
