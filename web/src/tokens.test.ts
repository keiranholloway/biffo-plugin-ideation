/** The palette belongs to `@biffo/design-tokens`, not to this app.
 *
 * This file used to hardcode every colour, including a brand blue (`#4338ca`)
 * that was not the platform's (`#5457ee`). The Ideation Engine is embedded in
 * the portal as a same-origin iframe, so the two sat next to each other on
 * screen and read as two different products. A third plugin had a third blue.
 *
 * These checks exist because the failure is *invisible in isolation*: an app
 * with its own palette looks perfectly fine on its own, and only looks wrong
 * beside the thing it is embedded in — which no unit test and no build ever
 * puts it next to.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// Read off disk rather than imported: Vitest stubs CSS imports (`css: false`),
// so `import css from './index.css?raw'` hands back an empty string and every
// check below passes vacuously.
const SRC = join(process.cwd(), 'src')
const CSS = readFileSync(join(SRC, 'index.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

// The published surface, read from the installed package rather than restated
// here — a second list is one more thing to drift.
const PACKAGE_TOKENS = readFileSync(
  join(process.cwd(), 'node_modules/@biffo/design-tokens/tokens.css'),
  'utf8',
)

describe('design tokens', () => {
  it('imports the shared tokens, so the variables it uses are actually defined', () => {
    // Without the import every `var(--brand)` falls back to nothing and the app
    // renders unstyled — and nothing else would fail.
    expect(CSS).toMatch(/@import\s+['"]@biffo\/design-tokens\/tokens\.css['"]/)
  })

  it('does not re-declare a token the shared package owns', () => {
    const shared = new Set([...PACKAGE_TOKENS.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]))
    const localised = [...CSS.matchAll(/(--[a-z0-9-]+)\s*:/g)]
      .map((m) => m[1])
      .filter((name) => shared.has(name))

    // A local copy silently wins over the import, so the app would look right
    // while being disconnected from the platform's definition.
    expect([...new Set(localised)]).toEqual([])
  })

  it('does not hardcode a colour the token set already names', () => {
    // Only the values the platform owns. Incidental tints this app invented for
    // itself are fine and deliberately not policed — the point is that the
    // *shared* decisions come from one place.
    const owned = ['#5457ee', '#4043c9', '#eef0ff', '#f6f7fb', '#0f172a', '#545d72', '#e7e9f1']
    const declarations = CSS.replace(/@import[^;]+;/g, '')

    expect(owned.filter((hex) => declarations.toLowerCase().includes(hex))).toEqual([])
  })

  it('no longer carries the brand blue that was not the platform', () => {
    expect(CSS).not.toContain('#4338ca')
  })
})
