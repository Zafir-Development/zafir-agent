import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, vi } from 'vitest'
import { generateIcons } from '../scripts/generate-icons.mjs'

test('the real wrapper builds and checks native icon artifacts in an independent output', () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-icons-'))
  const env = { ...process.env, HERMES_HOME: path.join(out, 'home'),
    HERMES_RUNTIME_DIR: path.join(out, 'tools'), HERMES_PAYLOAD_TAG: 'v1.2.3', HERMES_BUILD_COMMIT: '',
    PYTHONPATH: path.join(out, 'foreign-site'), PYTHONHOME: path.join(out, 'foreign-python') }
  try {
    const args = ['--source', fileURLToPath(new URL('..', import.meta.url)), '--out', out]
    expect(generateIcons(args, { env })).toBe(0)
    // Retained outputs: the shared brand master and the dashboard favicon. The
    // desktop app icon outputs went with the desktop packaging removal.
    const svg = fs.readFileSync(path.join(out, 'assets/icon-master.svg'), 'utf8')
    expect(svg).toContain('<svg')
    const ico = fs.readFileSync(path.join(out, 'web/public/favicon.ico'))
    expect(ico.subarray(0, 4)).toEqual(Buffer.from([0, 0, 1, 0]))
    expect(generateIcons([...args, '--check'], { env })).toBe(0)
    expect(env.PYTHONPATH).toBe(path.join(out, 'foreign-site'))
  } finally {
    fs.rmSync(out, { recursive: true, force: true })
  }
}, 180_000)

test('failed icon processes cannot report a successful build', () => {
  expect(generateIcons([], { run: () => ({ status: 7 }), env: {} })).toBe(7)
  expect(generateIcons([], { run: () => ({ status: null, signal: 'SIGTERM' }), env: {} })).toBe(1)
  const error = vi.spyOn(console, 'error').mockImplementation(() => {})
  try {
    expect(generateIcons([], { run: () => ({ error: new Error('prepared Python missing') }), env: {} })).toBe(1)
    expect(error).toHaveBeenCalledWith(expect.stringContaining('failed to launch'), 'prepared Python missing')
  } finally {
    error.mockRestore()
  }
})
