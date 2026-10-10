import { defineConfig } from '@playwright/test'

// E2E against a DEPLOYED environment (dev), not a local server: the plugin UI is
// served by the shared plugin host, behind the portal's Cognito session.
//
//   E2E_BASE_URL       origin of the deployed portal (dev URL, from config)
//   E2E_TEST_USERNAME  } dev test persona; e2e/global-setup.ts signs it in and
//   E2E_TEST_PASSWORD  } writes the storageState used by the spec
//   E2E_STORAGE_STATE  alternative: a ready storageState JSON (skips sign-in)
//
// Run: pnpm --dir web e2e   (CI: .github/workflows/e2e-dev.yml)
const hasPersona = !!process.env.E2E_TEST_USERNAME && !!process.env.E2E_TEST_PASSWORD
const storageState =
  process.env.E2E_STORAGE_STATE ?? (hasPersona ? 'test-results/.auth/state.json' : undefined)

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 90_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL,
    storageState,
    trace: 'retain-on-failure',
  },
})
