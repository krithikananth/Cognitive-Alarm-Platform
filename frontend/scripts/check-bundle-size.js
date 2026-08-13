/**
 * Fails the build when the shipped bundle grows past the agreed budget.
 *
 * Sizes are measured gzipped because that is what a browser actually
 * downloads; raw byte counts drift with minifier changes that cost users
 * nothing. Budgets live in performance-budget.json.
 *
 * Usage: node scripts/check-bundle-size.js [buildDir]
 */
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const ROOT = path.join(__dirname, '..');
const BUILD_DIR = path.resolve(process.argv[2] || path.join(ROOT, 'build'));
const BUDGET_FILE = path.join(ROOT, 'performance-budget.json');

function gzipKB(file) {
  return zlib.gzipSync(fs.readFileSync(file), { level: 9 }).length / 1024;
}

function main() {
  const manifestPath = path.join(BUILD_DIR, 'asset-manifest.json');
  if (!fs.existsSync(manifestPath)) {
    console.error(`[bundle-size] no build found at ${BUILD_DIR} — run "npm run build" first`);
    process.exit(1);
  }

  const { budgets, requireLazyChunks } = JSON.parse(fs.readFileSync(BUDGET_FILE, 'utf8'));
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const resolve = (assetPath) => path.join(BUILD_DIR, assetPath.replace(/^\//, ''));

  const entrypoints = manifest.entrypoints.map(resolve);
  const initialJsKB = entrypoints
    .filter((f) => f.endsWith('.js'))
    .reduce((sum, f) => sum + gzipKB(f), 0);
  const cssKB = entrypoints
    .filter((f) => f.endsWith('.css'))
    .reduce((sum, f) => sum + gzipKB(f), 0);

  const jsDir = path.join(BUILD_DIR, 'static', 'js');
  const jsFiles = fs.readdirSync(jsDir).filter((f) => f.endsWith('.js'));
  const totalJsKB = jsFiles.reduce((sum, f) => sum + gzipKB(path.join(jsDir, f)), 0);

  const lazyChunks = jsFiles
    .filter((f) => f.endsWith('.chunk.js'))
    .map((f) => ({ name: f, kb: gzipKB(path.join(jsDir, f)) }))
    .sort((a, b) => b.kb - a.kb);
  const largestLazyKB = lazyChunks.length ? lazyChunks[0].kb : 0;

  const checks = [
    ['initial JS (gzip)', initialJsKB, budgets.initialJsGzipKB],
    ['total JS (gzip)', totalJsKB, budgets.totalJsGzipKB],
    ['CSS (gzip)', cssKB, budgets.cssGzipKB],
    ['largest lazy chunk (gzip)', largestLazyKB, budgets.largestLazyChunkGzipKB],
  ];

  const failures = [];
  for (const [label, actual, limit] of checks) {
    const ok = actual <= limit;
    const pct = ((actual / limit) * 100).toFixed(0);
    console.log(
      `${ok ? 'PASS' : 'FAIL'}  ${label.padEnd(26)} ${actual.toFixed(1).padStart(7)} kB  ` +
      `/ ${String(limit).padStart(4)} kB budget (${pct}%)`
    );
    if (!ok) failures.push(`${label}: ${actual.toFixed(1)} kB exceeds ${limit} kB`);
  }

  // A collapsed bundle would pass every size budget while destroying the
  // route splitting, so assert the chunks still exist.
  const splitOk = lazyChunks.length >= requireLazyChunks;
  console.log(
    `${splitOk ? 'PASS' : 'FAIL'}  ${'lazy route chunks'.padEnd(26)} ${String(lazyChunks.length).padStart(7)}` +
    `     / ${requireLazyChunks} minimum`
  );
  if (!splitOk) {
    failures.push(
      `code splitting regressed: ${lazyChunks.length} lazy chunks, expected >= ${requireLazyChunks}`
    );
  }

  if (failures.length) {
    console.error('\n[bundle-size] performance budget exceeded:');
    failures.forEach((f) => console.error(`  - ${f}`));
    console.error('\nEither shrink the bundle or justify a new budget in performance-budget.json.');
    process.exit(1);
  }

  console.log('\n[bundle-size] all budgets met.');
}

main();
