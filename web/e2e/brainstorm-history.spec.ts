import { expect, test, type Page } from '@playwright/test'

// Brain-Storm history column (#250 / PR 252) on the deployed UI.
// Seeds two brain-storms through the plugin API (intake only, no research run),
// then clicks through the column: open + highlight, delete, "New brain-storm".

const UI = '/api/v1/plugins/ideation/ui/'
const API = '/api/v1/plugins/ideation'

test.skip(
  !process.env.E2E_BASE_URL ||
    !(
      process.env.E2E_STORAGE_STATE ||
      (process.env.E2E_TEST_USERNAME && process.env.E2E_TEST_PASSWORD)
    ),
  'set E2E_BASE_URL and either E2E_TEST_USERNAME/E2E_TEST_PASSWORD or E2E_STORAGE_STATE',
)

async function idToken(page: Page): Promise<string> {
  const token = await page.evaluate(() => {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i) ?? ''
      if (k.startsWith('CognitoIdentityServiceProvider.') && k.endsWith('.idToken')) {
        return localStorage.getItem(k)
      }
    }
    return null
  })
  expect(token, 'signed-in Cognito id token in localStorage').toBeTruthy()
  return token as string
}

async function seed(page: Page, token: string, target: string): Promise<string> {
  const res = await page.request.post(`${API}/brainstorm/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { target, geography: 'E2E-land', problem: 'e2e history column check' },
  })
  expect(res.ok(), `seed brain-storm: ${res.status()}`).toBeTruthy()
  return (await res.json()).session_id as string
}

async function remove(page: Page, token: string, id: string) {
  await page.request.post(`${API}/brainstorm/sessions/${id}/delete`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

test('Brain-Storm history column: open, highlight, delete, new brain-storm', async ({ page }) => {
  const run = Date.now().toString(36)
  const keep = `E2E keep ${run}`
  const doomed = `E2E doomed ${run}`

  await page.goto(UI)
  const token = await idToken(page)
  const ids: string[] = []
  try {
    ids.push(await seed(page, token, keep))
    ids.push(await seed(page, token, doomed))
    await page.reload()

    // The column exists on the Brain-Storm tab and lists both rows.
    const column = page.locator('nav.ide-sidebar')
    await expect(column).toBeVisible()
    await expect(column.getByRole('button', { name: 'New brain-storm' })).toBeVisible()
    const keepRow = column.locator('.ide-sidebar-item', { hasText: keep })
    const doomedRow = column.locator('.ide-sidebar-item', { hasText: doomed })
    await expect(keepRow).toBeVisible()
    await expect(doomedRow).toBeVisible()
    await expect(page.getByText('Your past brain-storms')).toHaveCount(0)

    // Open a past brain-storm: its row is highlighted and the column stays.
    await keepRow.click()
    await expect(keepRow).toHaveClass(/ide-sidebar-item--active/)
    await expect(doomedRow).not.toHaveClass(/ide-sidebar-item--active/)
    await expect(column).toBeVisible()
    await expect(page.getByLabel('Problem or idea')).toHaveCount(0)

    // Delete the OTHER one: the open view is left alone.
    page.once('dialog', (d) => void d.accept())
    await column.getByRole('button', { name: `Delete ${doomed}` }).click()
    await expect(doomedRow).toHaveCount(0)
    await expect(keepRow).toHaveClass(/ide-sidebar-item--active/)

    // New brain-storm returns to a fresh intake and clears the highlight.
    await column.getByRole('button', { name: 'New brain-storm' }).click()
    const problem = page.getByLabel('Problem or idea')
    await expect(problem).toBeVisible()
    await expect(problem).toHaveValue('')
    await expect(keepRow).not.toHaveClass(/ide-sidebar-item--active/)
    await expect(keepRow).toBeVisible()
  } finally {
    for (const id of ids) await remove(page, token, id)
  }
})
