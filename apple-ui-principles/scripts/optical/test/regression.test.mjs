import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { analyzeSvg, checkShape, checkIconSet } from '../icon.mjs';
import { checkCss } from '../rule.mjs';
import { checkTsx } from '../rule.mjs';
import { buildReport } from '../report.mjs';

const cli = fileURLToPath(new URL('../cli.mjs', import.meta.url));
const fixture = (name) => fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url));
const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
const near = (actual, expected, eps = 1e-3) =>
  assert.ok(Math.abs(actual - expected) < eps, `${actual} != ${expected} (±${eps})`);

const svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">${body}</svg>`;

// --- geometry: refusing to invent numbers -----------------------------------

test('an SVG with no ink reports unknown, never a fabricated offset', () => {
  const shape = analyzeSvg(svg(''));
  const report = checkShape(shape, { mode: 'standalone', target: 'empty.svg' });
  assert.equal(report.verdict, 'unknown');
  assert.ok(
    report.findings.every((f) => f.id !== 'geometry/centroid' || f.verdict === 'unknown'),
    JSON.stringify(report.findings, null, 2),
  );
  assert.equal(report.findings[0].id, 'geometry/no-ink');
});

test('fill-rule="evenodd" subtracts a same-winding hole', () => {
  const path = 'M4 4 H20 V20 H4 Z M8 11 H19 V19 H8 Z';
  const nonzero = analyzeSvg(svg(`<path d="${path}"/>`));
  const evenodd = analyzeSvg(svg(`<path fill-rule="evenodd" d="${path}"/>`));

  // non-zero: both subpaths wind the same way, so they add up
  near(nonzero.ink.area, 256 + 88, 1e-6);
  // even-odd: 256 - 88 = 168, centroid pulled towards the light corner
  near(evenodd.ink.area, 168, 1e-6);
  const expectedCx = (256 * 12 - 88 * 13.5) / 168;
  near(evenodd.ink.centroid.cx, expectedCx, 1e-6);
});

test('geometry inside defs / clipPath is not ink', () => {
  const inDefs = analyzeSvg(
    svg('<defs><rect x="1" y="1" width="2" height="2"/></defs><rect x="7" y="7" width="10" height="10"/>'),
  );
  near(inDefs.ink.bbox.minX, 7, 1e-6);
  near(inDefs.ink.bbox.maxX, 17, 1e-6);

  const inClip = analyzeSvg(
    svg('<clipPath id="c"><rect x="0" y="0" width="8" height="8"/></clipPath><rect x="7" y="7" width="10" height="10"/>'),
  );
  near(inClip.ink.bbox.minX, 7, 1e-6);
});

test('clip-path or mask makes the ink unverifiable instead of wrong', () => {
  const shape = analyzeSvg(
    svg('<clipPath id="c"><rect x="0" y="0" width="8" height="8"/></clipPath><rect x="7" y="7" width="10" height="10" clip-path="url(#c)"/>'),
  );
  const report = checkShape(shape, { mode: 'standalone', target: 'clipped.svg' });
  assert.equal(report.verdict, 'unknown');
  assert.ok(report.findings.some((f) => f.id === 'geometry/unresolved-graphics'));
});

test('<use> is resolved at its x/y offset', () => {
  const shape = analyzeSvg(
    svg('<defs><path id="p" d="M2 2 H6 V6 H2 Z"/></defs><use href="#p" x="12" y="12"/>'),
  );
  near(shape.ink.bbox.minX, 14, 1e-6);
  near(shape.ink.bbox.maxX, 18, 1e-6);
});

test('presentation attributes inside style are honoured', () => {
  const shape = analyzeSvg(svg('<path style="fill:none;stroke:#000;stroke-width:2" d="M6 12 H18"/>'));
  assert.equal(shape.strokeOnly, true);
  near(shape.ink.bbox.minY, 11, 1e-6);
  near(shape.ink.bbox.maxY, 13, 1e-6);
});

test('display:none subtrees are not ink', () => {
  const shape = analyzeSvg(
    svg('<g display="none"><rect x="0" y="0" width="4" height="4"/></g><rect x="7" y="7" width="10" height="10"/>'),
  );
  near(shape.ink.bbox.minX, 7, 1e-6);
});

// --- policy must not rewrite categorical verdicts ----------------------------

test('forced verdicts survive a policy override', () => {
  const report = buildReport({
    target: 'x.css',
    mode: 'rule',
    policy: { source: 'custom', path: 'p.json', toleranceScale: 4 },
    findings: [
      { id: 'rule/a', layer: 'exact', forcedVerdict: 'unknown', pixel: false, offset: 0, evidence: 'e' },
      { id: 'rule/b', layer: 'exact', forcedVerdict: 'off', pixel: false, offset: 0, evidence: 'e' },
    ],
  });
  assert.equal(report.findings[0].verdict, 'unknown');
  assert.equal(report.findings[1].verdict, 'off');
  assert.equal(report.policy_source, 'custom');
});

test('--policy cannot launder an unparseable stylesheet into ok', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-pol-'));
  const policy = join(dir, 'p.json');
  writeFileSync(policy, JSON.stringify({ toleranceScale: 4 }));
  const result = run('check', fixture('css/broken.css'), '--policy', policy, '--json');
  assert.equal(result.status, 2, result.stdout);
  assert.equal(JSON.parse(result.stdout).verdict, 'unknown');
});

// --- css tokeniser ----------------------------------------------------------

test('declarations before a nested rule are not swallowed', () => {
  const css = `.card {
  display: flex;
  text-box: trim-both cap alphabetic;
  & .title { color: red; }
}`;
  const report = checkCss(css, { target: 'nest.css' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'off');
});

test('a nested rule alone does not hide the parent declarations that follow it', () => {
  const css = `.card {
  & .title { color: red; }
  display: flex;
  text-box: trim-both;
}`;
  const report = checkCss(css, { target: 'nest2.css' });
  assert.equal(report.findings.find((x) => x.id === 'rule/text-box-in-flex')?.verdict, 'off');
});

// --- jsx --------------------------------------------------------------------

test('an arrow function inside an attribute does not corrupt the tree', () => {
  const tsx = `<div className="rounded-xl p-4"><Icon onSelect={() => (a > b)} /></div>
<div className="rounded-lg"><span /></div>`;
  const report = checkTsx(tsx, { target: 'arrow.tsx' });
  assert.equal(
    report.findings.filter((f) => f.id === 'rule/non-concentric-radius').length,
    0,
    'the second div is a sibling, not a child',
  );
});

test('clsx literals are read instead of being skipped', () => {
  const tsx = `<button className={clsx('flex', 'text-box-trim')} />`;
  const report = checkTsx(tsx, { target: 'clsx.tsx' });
  assert.equal(report.findings.find((f) => f.id === 'rule/text-box-in-flex')?.verdict, 'off');
});

test('text-box-edge alone is not a trimming declaration', () => {
  const report = checkTsx('<div className="flex text-box-edge-cap" />', { target: 'edge.tsx' });
  assert.equal(
    report.findings.filter((f) => f.id === 'rule/text-box-in-flex').length,
    0,
    JSON.stringify(report.findings, null, 2),
  );
});

test('padding larger than the outer radius is reported as an outer-radius defect', () => {
  const report = checkTsx('<div className="rounded-xl p-4"><span className="rounded-lg" /></div>', {
    target: 'pgt.tsx',
  });
  const f = report.findings.find((x) => x.radius === 'exceeds');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.ok(!/calc\(.*-/.test(f.suggested.value), `negative calc leaked: ${f.suggested.value}`);
});

test('unequal px/py padding refuses to guess the elliptical radius', () => {
  const report = checkTsx('<div className="rounded-xl px-4 py-1"><span className="rounded-md" /></div>', {
    target: 'ellipse.tsx',
  });
  const f = report.findings.find((x) => x.id === 'rule/non-concentric-radius');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'unknown');
});

// --- cli edge cases ---------------------------------------------------------

test('--mode keyline on a single file is a usage error', () => {
  const result = run('check', fixture('icons/play.svg'), '--mode', 'keyline');
  assert.equal(result.status, 64, result.stdout + result.stderr);
});

test('a missing policy file is a usage error, not an unknown', () => {
  const result = run('check', fixture('icons/play.svg'), '--policy', '/nonexistent/policy.json');
  assert.equal(result.status, 64, result.stdout + result.stderr);
});

test('a policy with a non-positive scale is rejected', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-pol0-'));
  const policy = join(dir, 'p.json');
  writeFileSync(policy, JSON.stringify({ toleranceScale: 0 }));
  const result = run('check', fixture('icons/play.svg'), '--policy', policy);
  assert.equal(result.status, 64, result.stdout + result.stderr);
});

test('categorical findings do not print a fake pixel offset', () => {
  const result = run('check', fixture('css/flex-textbox.css'));
  assert.match(result.stdout, /rule\/text-box-in-flex/);
  assert.ok(!/\+1px/.test(result.stdout), result.stdout);
});

// --- font subcommand --------------------------------------------------------

function makeTtf() {
  const head = Buffer.alloc(54);
  head.writeUInt32BE(0x00010000, 0);
  head.writeUInt16BE(1000, 18); // unitsPerEm

  const hhea = Buffer.alloc(36);
  hhea.writeInt16BE(800, 4); // ascender
  hhea.writeInt16BE(-200, 6); // descender

  const os2 = Buffer.alloc(96);
  os2.writeUInt16BE(4, 0); // version
  os2.writeInt16BE(700, 88); // sCapHeight

  const tables = [
    ['head', head],
    ['hhea', hhea],
    ['OS/2', os2],
  ];
  const header = Buffer.alloc(12 + tables.length * 16);
  header.writeUInt32BE(0x00010000, 0);
  header.writeUInt16BE(tables.length, 4);

  let offset = header.length;
  const bodies = [];
  tables.forEach(([tag, body], i) => {
    header.write(tag, 12 + i * 16, 'latin1');
    header.writeUInt32BE(offset, 12 + i * 16 + 8);
    header.writeUInt32BE(body.length, 12 + i * 16 + 12);
    bodies.push(body);
    offset += body.length;
  });
  return Buffer.concat([header, ...bodies]);
}

test('the font subcommand reports the cap-midpoint offset', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-font-'));
  const font = join(dir, 'test.ttf');
  writeFileSync(font, makeTtf());
  const result = run('font', font, '--size', '16');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /-0\.8px/);
});

test('a woff2 font is refused with a clear message', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-woff-'));
  const font = join(dir, 'test.woff2');
  writeFileSync(font, Buffer.concat([Buffer.from('wOF2', 'latin1'), Buffer.alloc(60)]));
  const result = run('font', font, '--size', '16');
  assert.equal(result.status, 2, result.stdout + result.stderr);
  assert.match(result.stderr, /WOFF2/);
});

test('an icon set of <use> icons is measured, not silently zeroed', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-use-'));
  for (const [name, x] of [
    ['a', 0],
    ['b', 4],
    ['c', 8],
  ]) {
    writeFileSync(
      join(dir, `${name}.svg`),
      svg(`<defs><rect id="r" width="6" height="6"/></defs><use href="#r" x="${x}" y="0"/>`),
    );
  }
  const report = await checkIconSet(dir);
  assert.notEqual(report.verdict, 'unknown', 'resolvable <use> icons must produce a real norm');
  for (const f of report.findings) {
    // 6x6 ink in a 24x24 canvas = 36/576, not the 0 the reviewer saw
    assert.match(f.evidence, /fill ratio=0\.06/, f.evidence);
  }
});

test('fixture round-trip still works', () => {
  const text = readFileSync(fixture('icons/play.svg'), 'utf8');
  assert.match(text, /M8 5/);
});
