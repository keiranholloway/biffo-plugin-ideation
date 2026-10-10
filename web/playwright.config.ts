import { defineConfig } from '@playwright/test'

// E2E against a DEPLOYED environment (dev), not a local server: the plugin UI is
// served by the shared plugin host, behind the portal's Cognito session.
//
//   E2E_BASE_URL       origin of the deployed portal, e.g. https://dev.example.com
//   E2E_STORAGE_STATE  path to a Playwright storageState JSON holding a signed-in
//                      founder's shared Cognito session (localStorage entries)
//
// Run: pnpm --dir web e2e
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL,
    storageState: process.env.E2E_STORAGE_STATE,
    trace: 'retain-on-failure',
  },
})
