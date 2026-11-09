// Product receipts belong to the compilers, not PM dependency receipts or profiles.
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { isMain } from './frontend-common.mjs'

const receiptName = 'hermes-build.json'
const workspaces = { tui: 'ui-tui', web: 'web' }
// Another product's output under a workspace is never this product's input.
const generated = new Set(['node_modules', 'dist', 'build', 'release', '.cache', '.git', 'coverage', 'test-results', 'playwright-report'])

// OS file-manager metadata is never a build input, and it can land in ANY hashed
// tree (source, output or a prepared dir) the moment the checkout is opened in
// Finder or Explorer mid-build — .DS_Store, AppleDouble ._* sidecars and
// .localized on macOS, Thumbs.db and Desktop.ini on Windows. Skip it everywhere
// so it can't flip a freshness hash and abort `hermes update` (#122632, #122803).
const osMetadata = name => {
  const base = name.split('/').pop()
  return base === '.DS_Store' || base === '.localized'
    || base === 'Thumbs.db' || base === 'Desktop.ini' || base.startsWith('._')
}

// buildTui bundles these source roots (including the Ink source alias), not
// the workspaces' documentation, test runners or other product recipes.
const tuiInputs = [
  ...['ui-tui', 'ui-tui/packages/hermes-ink', 'apps/shared'].flatMap(root => [
    `${root}/src`, `${root}/package.json`, `${root}/tsconfig.json`,
  ]),
  'tsconfig.json', 'package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', '.npmrc', 'pm/lock.json',
  'scripts/build/tui.mjs', 'scripts/build/frontend-common.mjs', 'scripts/build/freshness.mjs',
  'ui-tui/scripts/gateway_bootstrap.py', 'ui-tui/scripts/clipboard_image.py',
]

function productInputs(product) {
  if (product === 'tui') return tuiInputs
  const workspace = workspaces[product]
  if (!workspace) throw new Error(`Unknown frontend product: ${product}`)
  return [
    workspace, 'apps/shared', 'package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', '.npmrc', 'pm/lock.json',
    'scripts/build',
    'scripts/generate-icons.mjs', 'scripts/generate_icons.py',
    'assets', 'pyproject.toml', 'uv.lock',
  ]
}

function skipInput(product) {
  return name => {
    // Build scripts are inputs; workspace build directories are outputs.
    const parts = name.split('/')
    return (!name.startsWith('scripts/') && parts.some(part => generated.has(part)))
      || (product === 'tui' && (parts.includes('__tests__') || /\.(test|spec)(-d)?\.[cm]?[jt]sx?$/.test(name)))
      || parts.some(part => part.startsWith('.dist-') || part.startsWith('.staging-') || part === '__pycache__')
      || name.endsWith('.tsbuildinfo') || name.endsWith('.pyc')
  }
}

// Pre-order walk: a directory is reported before its sorted children.
function walkTree(root, inputs, skip, onEntry) {
  function visit(name) {
    if (osMetadata(name) || skip(name)) return
    const file = join(root, name)
    if (!existsSync(file)) return onEntry(name, 'missing')
    if (!statSync(file).isDirectory()) return onEntry(name, 'file')
    onEntry(name, 'directory')
    for (const child of readdirSync(file).sort()) visit(`${name}/${child}`)
  }
  for (const input of inputs) visit(input)
}

function treeHash(root, inputs, skip, contents = () => true) {
  const hash = createHash('sha256')
  walkTree(root, inputs, skip, (name, kind) => {
    hash.update(name.replaceAll('\\', '/')).update('\0')
    if (kind === 'file') hash.update(contents(name) ? readFileSync(join(root, name)) : 'file').update('\0')
    else hash.update(`${kind}\0`)
  })
  return hash.digest('hex')
}

export function sourceHash(source, product) {
  return treeHash(source, productInputs(product), skipInput(product))
}

function outputHash(out) {
  // Compiled product bytes must stay intact. A prepared native tree's binaries can
  // be signed after compilation; that ABI validation belongs to native preparation.
  return treeHash(out, readdirSync(out).sort(), name => name === receiptName || name === '.hermes-product',
    name => !name.split('/').includes('node_modules') && !name.startsWith('native/'))
}

export function buildInputs(source, product, prepared = {}) {
  return {
    sourceHash: sourceHash(source, product),
    prepared: Object.entries(prepared).sort().map(([name, path]) => ({
      name, path: resolve(path), hash: treeHash(resolve(path), ['.'], () => false),
    })),
  }
}

function preparedPaths(inputs) {
  return Object.fromEntries(inputs.prepared.map(({ name, path }) => [name, path]))
}

export function recordProduct({ source, product, out, inputs }) {
  if (JSON.stringify(buildInputs(source, product, preparedPaths(inputs))) !== JSON.stringify(inputs)) {
    throw new Error('Build inputs changed during compilation; retry the build')
  }
  writeFileSync(join(out, receiptName), JSON.stringify({
    schema: 1, product, platform: process.platform, arch: process.arch, node: process.versions.node,
    inputs, outputHash: outputHash(out),
  }) + '\n')
}

/** Validate output bytes against their receipt, independently of current inputs or host. */
export function outputIntact(out, product) {
  try {
    const saved = JSON.parse(readFileSync(join(out, receiptName), 'utf8'))
    return saved.schema === 1 && saved.product === product && saved.outputHash === outputHash(out)
  } catch { return false }
}

/** The receipt in ``out`` when it was written for ``product`` by this platform, arch and Node. */
function hostReceipt(out, product) {
  const saved = JSON.parse(readFileSync(join(out, receiptName), 'utf8'))
  return saved.schema === 1 && saved.product === product
    && saved.platform === process.platform && saved.arch === process.arch
    && saved.node === process.versions.node ? saved : null
}

export function productCurrent({ source, product, out, prepared }) {
  try {
    const saved = hostReceipt(out, product)
    const paths = saved && (prepared ?? preparedPaths(saved.inputs))
    return !!saved
      && JSON.stringify(saved.inputs) === JSON.stringify(buildInputs(source, product, paths))
      && saved.outputHash === outputHash(out)
  } catch { return false }
}

if (isMain(import.meta.url)) {
  const { values } = parseArgs({ options: {
    source: { type: 'string' }, product: { type: 'string' }, out: { type: 'string' },
  } })
  if (!values.source || !values.product || !values.out) throw new Error('--source, --product and --out are required')
  console.log(JSON.stringify(productCurrent(values)))
}
