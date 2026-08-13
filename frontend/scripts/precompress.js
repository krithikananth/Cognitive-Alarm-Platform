/**
 * Pre-compresses the production build so nginx can serve `.br`/`.gz` siblings
 * via brotli_static/gzip_static instead of compressing on every request.
 *
 * Offline compression can afford brotli quality 11 and zlib level 9, which
 * on-the-fly compression never uses because it would burn CPU per request.
 *
 * Usage: node scripts/precompress.js [buildDir]
 *        node scripts/precompress.js --verify [buildDir]
 */
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const args = process.argv.slice(2);
const VERIFY = args.includes('--verify');
const positional = args.filter((a) => !a.startsWith('--'));
const BUILD_DIR = path.resolve(positional[0] || path.join(__dirname, '..', 'build'));

const COMPRESSIBLE = new Set([
  '.js', '.mjs', '.css', '.html', '.json', '.svg', '.txt', '.map', '.webmanifest', '.ico',
]);

// Below this size the compressed response costs more than it saves once the
// extra headers and a filesystem lookup are accounted for.
const MIN_BYTES = 1024;

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.isFile()) out.push(full);
  }
  return out;
}

function brotli(buf) {
  return zlib.brotliCompressSync(buf, {
    params: {
      [zlib.constants.BROTLI_PARAM_QUALITY]: zlib.constants.BROTLI_MAX_QUALITY,
      [zlib.constants.BROTLI_PARAM_SIZE_HINT]: buf.length,
    },
  });
}

function candidates() {
  return walk(BUILD_DIR).filter((file) => {
    const ext = path.extname(file).toLowerCase();
    if (!COMPRESSIBLE.has(ext)) return false;
    return fs.statSync(file).size >= MIN_BYTES;
  });
}

// nginx serves brotli_static/gzip_static and silently falls back to on-the-fly
// compression when a sibling is missing, so absence has to be an explicit
// failure rather than a quiet performance loss.
function verify() {
  const assets = candidates();
  const missing = [];
  for (const file of assets) {
    const rel = path.relative(BUILD_DIR, file);
    for (const suffix of ['.br', '.gz']) {
      if (!fs.existsSync(`${file}${suffix}`) && !isIncompressible(file, suffix)) {
        missing.push(`${rel}${suffix}`);
      }
    }
  }
  if (missing.length) {
    console.error('[precompress] missing precompressed siblings:');
    missing.forEach((m) => console.error(`  - ${m}`));
    process.exit(1);
  }
  console.log(`[precompress] verified ${assets.length} assets have .br and .gz siblings`);
}

// A file whose compressed form was larger than the original is deliberately
// left without a sibling; re-check rather than treating it as a failure.
function isIncompressible(file, suffix) {
  const buf = fs.readFileSync(file);
  const out = suffix === '.br' ? brotli(buf) : zlib.gzipSync(buf, { level: 9 });
  return out.length >= buf.length;
}

function main() {
  if (!fs.existsSync(BUILD_DIR)) {
    console.error(`[precompress] build directory not found: ${BUILD_DIR}`);
    process.exit(1);
  }

  if (VERIFY) {
    verify();
    return;
  }

  let files = 0;
  let raw = 0;
  let br = 0;
  let gz = 0;

  for (const file of candidates()) {
    const buf = fs.readFileSync(file);
    const brBuf = brotli(buf);
    const gzBuf = zlib.gzipSync(buf, { level: 9 });

    // A compressed sibling larger than the original would make nginx serve
    // more bytes than it needs to, so drop it and let the plain file win.
    if (brBuf.length < buf.length) {
      fs.writeFileSync(`${file}.br`, brBuf);
      br += brBuf.length;
    } else {
      br += buf.length;
    }
    if (gzBuf.length < buf.length) {
      fs.writeFileSync(`${file}.gz`, gzBuf);
      gz += gzBuf.length;
    } else {
      gz += buf.length;
    }

    files += 1;
    raw += buf.length;
  }

  const kb = (n) => `${(n / 1024).toFixed(1)} kB`;
  console.log(
    `[precompress] ${files} files: raw ${kb(raw)} -> gzip ${kb(gz)} -> brotli ${kb(br)}`
  );
}

main();
