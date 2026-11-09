import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from 'vitest'

const script: string = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../scripts/sandbox/generate-e2e-matrix.mjs')
const TAGS: string = JSON.stringify(['v2026.6.19'])

interface Leg {
  name: string
  install_method: string
  update_method: string
}
type Matrices = Record<'linux' | 'windows' | 'macos', { include: Leg[] }>

function generate(route: string): Matrices {
  return JSON.parse(execFileSync(process.execPath, [script, '--tags', TAGS, '--route', route], { encoding: 'utf8' })) as Matrices
}

function legs(matrices: Matrices): Leg[] {
  return Object.values(matrices).flatMap(m => m.include)
}

function legNames(matrices: Matrices): string[] {
  return legs(matrices).map(leg => leg.name)
}

test('a leg name, or the job name GitHub shows for it, runs exactly that leg', () => {
  const leg: Leg | undefined = generate('all').windows.include.find(l =>
    l.name.includes('installer-script -> hermes-update')
  )

  expect(leg).toBeDefined()
  expect(legNames(generate(leg!.name))).toEqual([leg!.name])
  expect(legNames(generate(`${leg!.name} / e2e`))).toEqual([leg!.name])
})

test('an OS preset runs that OS whole and no other', () => {
  const all: Matrices = generate('all')
  const installer: Matrices = generate('installer')

  expect(legNames(installer)).toEqual(all.linux.include.map(l => l.name))
  expect(installer.windows.include).toEqual([])
  expect(installer.macos.include).toEqual([])
})

test('a route that selects nothing fails instead of running an empty green matrix', () => {
  expect(() => generate('windows: no-such-method')).toThrow()
})

test('every generated leg is a source install; no packaged or bundled route survives', () => {
  const all: Matrices = generate('all')

  expect(legs(all).every(leg => leg.install_method === 'installer-script')).toBe(true)
  expect(new Set(legs(all).map(leg => leg.update_method))).toEqual(
    new Set(['installer-script', 'hermes-update'])
  )
  expect(legNames(all).some(name => /desktop-app-update|packaged-app|open-app-update|bundled/.test(name))).toBe(false)
  expect(() => generate('windows-bundled')).toThrow()
  expect(() => generate('windows-desktop')).toThrow()
})

test('the pr route runs one script install updated by hermes update per OS start, nothing else', () => {
  const pr: Matrices = generate('pr')

  expect(legNames(pr).sort()).toEqual([
    'linux: installer-script -> hermes-update (HEAD -> NEXT)',
    'linux: installer-script -> hermes-update (v2026.6.19 -> HEAD)',
    'macos: installer-script -> hermes-update (v2026.6.19 -> HEAD)',
    'windows: installer-script -> hermes-update (HEAD -> NEXT)',
  ])
})
