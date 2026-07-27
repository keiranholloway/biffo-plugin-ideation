// Which base each admin call is sent to. Chat agents are proxied by this
// plugin's own admin app; the model catalog is a manifest-declared api_route
// that Core serves and the plugin host forwards (biffo-template#684). Sending
// the catalog through the admin app instead made the host call its own public
// path and forward on to Core — three hops, and the 500 in
// biffo-template#652 — so the base a catalog call uses is load-bearing, not
// cosmetic.
import { describe, it, expect, vi, afterEach } from 'vitest'

import { createApi } from './api'

const ADMIN_BASE = '/api/v1/plugins/ideation/admin'
const CATALOG_BASE = '/api/v1/plugins/ideation'

function mockFetch(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn(
    async () =>
      ({
        ok: true,
        json: async () => [],
        text: async () => '[]',
      }) as Response,
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function urlOf(fetchMock: ReturnType<typeof vi.fn>): string {
  return String(fetchMock.mock.calls[0][0])
}

describe('admin API bases', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends chat-agent calls to the plugin admin app', async () => {
    const fetchMock = mockFetch()

    await createApi(() => 'token').listChatAgents()

    expect(urlOf(fetchMock)).toBe(`${ADMIN_BASE}/chat-agents`)
  })

  it('sends the model-catalog list to the declared route, not the admin proxy', async () => {
    const fetchMock = mockFetch()

    await createApi(() => 'token').listModelCatalog()

    expect(urlOf(fetchMock)).toBe(`${CATALOG_BASE}/model-catalog`)
    expect(urlOf(fetchMock)).not.toContain('/admin/')
  })

  it.each([
    ['create', (api: ReturnType<typeof createApi>) => api.createModelCatalogEntry({} as never)],
    ['read', (api: ReturnType<typeof createApi>) => api.getModelCatalogEntry('entry-1')],
    ['update', (api: ReturnType<typeof createApi>) => api.updateModelCatalogEntry('entry-1', {})],
    ['delete', (api: ReturnType<typeof createApi>) => api.deleteModelCatalogEntry('entry-1')],
  ])('sends the model-catalog %s to the declared route too', async (_name, call) => {
    const fetchMock = mockFetch()

    await call(createApi(() => 'token'))

    expect(urlOf(fetchMock)).toContain(`${CATALOG_BASE}/model-catalog`)
    expect(urlOf(fetchMock)).not.toContain('/admin/')
  })

  it('still authorises every call with the portal session token', async () => {
    const fetchMock = mockFetch()

    await createApi(() => 'a-real-token').listModelCatalog()

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer a-real-token')
  })
})
