import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { analyzeSvg, checkShape, checkIconSet } from '../icon.mjs';
import { checkCss, classInfo } from '../rule.mjs';
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

  // non-zero: same winding inside a container means winding 2, which is still
  // one fill — the inner square adds nothing, it does not double the area.
  near(nonzero.ink.area, 256, 1e-6);
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

// --- round 2: even-odd limits, <use>, JSX syntax ----------------------------

test('evenodd with partially overlapping outlines refuses instead of inventing a centroid', () => {
  const shape = analyzeSvg(
    svg('<path fill-rule="evenodd" d="M2 2 H18 V18 H2 Z M10 10 H22 V22 H10 Z"/>'),
  );
  const report = checkShape(shape, { mode: 'standalone', target: 'xor.svg' });
  assert.equal(report.verdict, 'unknown');
  assert.match(report.findings.map((f) => f.evidence).join(' '), /overlapping-subpaths/);
});

test('evenodd hole sharing a corner with its container is still a hole', () => {
  const shape = analyzeSvg(svg('<path fill-rule="evenodd" d="M4 4 H20 V20 H4 Z M4 4 H12 V12 H4 Z"/>'));
  near(shape.ink.area, 192, 1e-6);
  near(shape.ink.centroid.cx, 2560 / 192, 1e-6);
  near(shape.ink.centroid.cy, 2560 / 192, 1e-6);
});

test('<use> pointing at a <symbol> renders the symbol content', () => {
  const shape = analyzeSvg(
    svg('<symbol id="s"><rect x="4" y="4" width="16" height="16"/></symbol><use href="#s"/>'),
  );
  near(shape.ink.bbox.minX, 4, 1e-6);
  near(shape.ink.bbox.maxX, 20, 1e-6);
  assert.equal(shape.noInk, false);
});

test('<use> honours its own transform', () => {
  const shape = analyzeSvg(
    svg('<defs><rect id="r" x="2" y="2" width="4" height="4"/></defs><use href="#r" transform="translate(10,10)"/>'),
  );
  near(shape.ink.bbox.minX, 12, 1e-6);
  near(shape.ink.bbox.maxX, 16, 1e-6);
});

test('commented-out JSX does not produce findings', () => {
  const tsx = `<div className="wrap">
  {/* <div className="flex text-box-trim">old</div> */}
  <span className="label" />
</div>`;
  const report = checkTsx(tsx, { target: 'comment.tsx' });
  assert.equal(report.findings.length, 0, JSON.stringify(report.findings, null, 2));
});

test('mutually exclusive class branches degrade to unknown', () => {
  const tsx = `<div className={clsx(stack ? 'flex' : 'block', 'text-box-trim')} />`;
  const report = checkTsx(tsx, { target: 'ternary.tsx' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'unknown');
});

test('template interpolations keep their literal tokens and stay ambiguous', () => {
  const tsx = '<div className={`flex ${on ? "text-box-trim" : ""}`} />';
  const report = checkTsx(tsx, { target: 'template.tsx' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'unknown');
});

test('a generic component does not re-parent its siblings', () => {
  const tsx = `<div className="rounded-xl p-2"><List<Item> /></div>
<div className="rounded-none"><span className="rounded-lg" /></div>`;
  const report = checkTsx(tsx, { target: 'generic.tsx' });
  assert.equal(
    report.findings.filter((f) => f.id === 'rule/non-concentric-radius').length,
    0,
    JSON.stringify(report.findings, null, 2),
  );
});

test('fragments are transparent in the element tree', () => {
  const tsx = '<div className="rounded-xl p-2"><><span className="rounded-none" /></></div>';
  const report = checkTsx(tsx, { target: 'fragment.tsx' });
  const f = report.findings.find((x) => x.id === 'rule/non-concentric-radius');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
});

// --- round 3: crossing outlines, comparison operators, && conditions --------

test('evenodd outlines that cross without containing a vertex are refused', () => {
  const shape = analyzeSvg(svg('<path fill-rule="evenodd" d="M2 6 H22 V10 H2 Z M12 2 H18 V22 H12 Z"/>'));
  const report = checkShape(shape, { mode: 'standalone', target: 'plus.svg' });
  assert.equal(report.verdict, 'unknown');
  assert.match(report.findings.map((f) => f.evidence).join(' '), /overlapping-subpaths/);
});

test('a comparison inside children does not swallow the rest of the file', () => {
  const tsx = `<>
  <div className="rounded-xl p-2"><span className="rounded" /></div>
  <div>{a < b}</div>
  <div className="flex text-box-trim"><span /></div>
</>`;
  const report = checkTsx(tsx, { target: 'compare.tsx' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'off');
});

test('&& conditions are as conditional as ternary branches', () => {
  const tsx = `<div className={clsx('flex', enabled && 'text-box-trim')} />`;
  const report = checkTsx(tsx, { target: 'and.tsx' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'unknown');
});

test('a string literal containing markup is not an element', () => {
  const tsx = `<div className="rounded-xl p-2">
  {'<div className="rounded-none">'}
  <span className="rounded" />
</div>`;
  const report = checkTsx(tsx, { target: 'literal.tsx' });
  assert.equal(
    report.findings.filter((f) => f.id === 'rule/non-concentric-radius').length,
    0,
    JSON.stringify(report.findings, null, 2),
  );
});

test('a question mark inside a static arbitrary value is not a condition', () => {
  const tsx = `<div className="flex text-box-trim [content:'?']"><span /></div>`;
  const report = checkTsx(tsx, { target: 'arbitrary.tsx' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'off');
});

test('an interpolated radius fragment is not rounded-*', () => {
  const tsx = `<div className="rounded-xl p-1"><span className={'rounded-' + size} /></div>`;
  const report = checkTsx(tsx, { target: 'interp.tsx' });
  assert.equal(
    report.findings.filter((f) => f.id === 'rule/non-concentric-radius').length,
    0,
    JSON.stringify(report.findings, null, 2),
  );
});

// --- round 4: nested viewports, display normalisation, context merging ------

test('a <symbol viewBox> is scaled into the viewport <use> gives it', () => {
  // 10-unit artwork placed in a 24-unit viewport must cover 0..24. Measuring it
  // as 0..10 reports a 7px offset that does not exist.
  const shape = analyzeSvg(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="100" height="100">` +
      '<symbol id="s" viewBox="0 0 10 10"><rect x="0" y="0" width="10" height="10"/></symbol>' +
      '<use href="#s"/></svg>',
  );
  near(shape.ink.bbox.maxX, 24, 1e-6);
  near(shape.ink.bbox.maxY, 24, 1e-6);
});

test('<use width height> overrides the default 100% viewport', () => {
  const shape = analyzeSvg(
    svg(
      '<symbol id="s" viewBox="0 0 10 10"><rect x="0" y="0" width="10" height="10"/></symbol>' +
        '<use href="#s" x="4" y="4" width="12" height="12"/>',
    ),
  );
  near(shape.ink.bbox.minX, 4, 1e-6);
  near(shape.ink.bbox.maxX, 16, 1e-6);
});

test('a nested <svg viewBox> rescales its children', () => {
  const shape = analyzeSvg(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">` +
      '<svg x="10" y="10" width="20" height="20" viewBox="0 0 10 10">' +
      '<rect x="0" y="0" width="10" height="10"/></svg></svg>',
  );
  near(shape.ink.bbox.minX, 10, 1e-6);
  near(shape.ink.bbox.maxX, 30, 1e-6);
});

test('a relative nested viewport is not silently taken as zero', () => {
  const shape = analyzeSvg(
    svg('<svg width="2em" height="2em"><rect x="0" y="0" width="4" height="4"/></svg>'),
  );
  assert.ok(shape.unresolved.includes('viewport-relative-units'), JSON.stringify(shape.unresolved));
});

test('root width/height turn user units into rendered px', () => {
  const shape = analyzeSvg(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="48" height="48">` +
      '<rect x="0" y="0" width="4" height="4"/></svg>',
  );
  near(shape.unitScale, 2, 1e-9);
  const report = checkShape(shape, { mode: 'standalone', target: 'scaled.svg' });
  const f = report.findings.find((x) => x.id === 'geometry/ink-bbox');
  // ink centre is (2,2), viewBox centre (12,12): -10 user units = -20 px.
  near(f.measured.dx, -20, 1e-6);
  assert.equal(f.measured.unit, 'px');
});

test('the viewBox suggestion and the measured offset agree in sign', () => {
  const shape = analyzeSvg(svg('<rect x="2" y="8" width="12" height="8"/>'));
  const report = checkShape(shape, { mode: 'standalone', target: 'lo.svg' });
  const f = report.findings.find((x) => x.id === 'geometry/ink-bbox');
  // ink centre x is 8, viewBox centre 12 -> dx = -4, so the origin must move -4.
  near(f.measured.dx, -4, 1e-6);
  assert.equal(f.suggested.viewBox, '-4 0 24 24', JSON.stringify(f.suggested));
  assert.equal(f.suggested.value, '-4px / 0px', JSON.stringify(f.suggested));
});

test('the centroid suggestion covers both axes and is not a translation', () => {
  const shape = analyzeSvg(svg('<path d="M4 4 L16 6 L10 18 Z"/>'));
  const report = checkShape(shape, { mode: 'standalone', target: 'diag.svg' });
  const f = report.findings.find((x) => x.id === 'geometry/centroid');
  // Translating the artwork cannot change a centroid offset: the centroid and the
  // ink box move together, so the suggestion has to say "redraw", not "shift".
  assert.equal(f.suggested.kind, 'redraw');
  assert.equal(f.suggested.value, 'move the visual mass 0px / 1.67px', JSON.stringify(f.suggested));
});

test('visibility:hidden is inherited but a descendant can restore it', () => {
  const shape = analyzeSvg(
    svg(
      '<g visibility="hidden"><rect x="0" y="0" width="4" height="4"/>' +
        '<rect x="10" y="10" width="4" height="4" visibility="visible"/></g>',
    ),
  );
  near(shape.ink.bbox.minX, 10, 1e-6);
  near(shape.ink.bbox.maxX, 14, 1e-6);
});

test('display:flex !important still makes text-box a no-op', () => {
  const report = checkCss('.a{display:flex!important;text-box:trim-both}', { target: 'imp.css' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'off');
});

test('display from a var() is unknown, not assumed to be flex', () => {
  const report = checkCss('.a{display:var(--d);text-box:trim-both}', { target: 'var.css' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.equal(f.verdict, 'unknown');
  assert.match(f.evidence, /var\(\)/);
});

test('text-box:normal is the initial value, not a request to trim', () => {
  const report = checkCss('.c{display:flex;text-box:normal}', { target: 'normal.css' });
  assert.equal(report.findings.length, 0, JSON.stringify(report.findings, null, 2));
});

test('shorthand and longhand resolve in source order', () => {
  const on = checkCss('.x{text-box:normal;text-box-trim:trim-both}', { target: 'on.css' });
  assert.equal(on.findings.length, 1, JSON.stringify(on.findings, null, 2));
  const off = checkCss('.y{text-box:trim-both;text-box-trim:none}', { target: 'off.css' });
  assert.equal(off.findings.length, 0, JSON.stringify(off.findings, null, 2));
});

test('display supplied by an @media block joins the base rule', () => {
  const report = checkCss('.a{text-box:trim-both}@media (min-width:600px){.a{display:flex}}', {
    target: 'media.css',
  });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'off');
});

test('disagreeing display across contexts degrades to unknown', () => {
  const report = checkCss(
    '.c{display:flex;text-box:trim-both}@media (min-width:600px){.c{display:block}}',
    { target: 'conflict.css' },
  );
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.equal(f.verdict, 'unknown');
  assert.match(f.evidence, /differently/);
});

test('tailwind important modifiers do not hide the flex utility', () => {
  for (const cls of ['flex! text-box-trim', '!flex text-box-trim']) {
    const report = checkTsx(`<div className="${cls}" />`, { target: 'bang.tsx' });
    const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
    assert.ok(f, `${cls}: ${JSON.stringify(report.findings, null, 2)}`);
    assert.equal(f.verdict, 'off', cls);
  }
});

test('text-box with no display utility at all is unknown, not a pass', () => {
  const report = checkTsx('<div className="text-box-trim" />', { target: 'nodisp.tsx' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.equal(f.verdict, 'unknown');
});

test('a sub-pixel nudge is inside tolerance and is not reported', () => {
  const report = checkCss('.h{font-size:16px;margin-top:.5px}', { target: 'tiny.css' });
  assert.equal(report.findings.length, 0, JSON.stringify(report.findings, null, 2));
});

test('--size on check is refused instead of ignored', () => {
  const r = run('check', fixture('icons/play.svg'), '--size', '48');
  assert.equal(r.status, 64, r.stderr);
  assert.match(r.stderr, /font/);
});

test('a percentage <use> resolves against the nearest viewport, not the root', () => {
  const shape = analyzeSvg(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">` +
      '<defs><symbol id="s" viewBox="0 0 10 10"><rect x="0" y="0" width="10" height="10"/></symbol></defs>' +
      '<svg x="10" y="10" width="20" height="20"><use href="#s" width="100%" height="100%"/></svg></svg>',
  );
  near(shape.ink.bbox.minX, 10, 1e-6);
  near(shape.ink.bbox.maxX, 30, 1e-6);
});

test('the unit scale is only claimed when both dimensions are absolute', () => {
  const box = '<rect x="0" y="0" width="4" height="4"/>';
  const head = (attrs) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ${attrs}>`;
  near(analyzeSvg(`${head('width="48" height="48"')}${box}</svg>`).unitScale, 2, 1e-9);
  // A lone width leaves the rendered box unknowable; claiming 2 would be a guess.
  const lone = analyzeSvg(`${head('width="48"')}${box}</svg>`);
  near(lone.unitScale, 1, 1e-9);
  assert.equal(lone.unitSource, 'assumed');
});

test('the report exposes how the unit scale was derived', () => {
  const assumed = checkShape(analyzeSvg(svg('<rect x="4" y="4" width="16" height="16"/>')), {
    target: 'a.svg',
  });
  assert.equal(assumed.unitScale, 1);
  assert.equal(assumed.unitSource, 'assumed');

  const declared = checkShape(
    analyzeSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="48" height="48">' +
        '<rect x="4" y="4" width="16" height="16"/></svg>',
    ),
    { target: 'b.svg' },
  );
  assert.equal(declared.unitScale, 2);
  assert.equal(declared.unitSource, 'declared');
});

test('a clip-path that provably contains the artwork is ignored', () => {
  // The Figma/Designer export pattern: a clip rect exactly the size of the canvas.
  const shape = analyzeSvg(
    svg(
      '<defs><clipPath id="c"><rect x="0" y="0" width="24" height="24"/></clipPath></defs>' +
        '<g clip-path="url(#c)"><rect x="4" y="4" width="16" height="16"/></g>',
    ),
  );
  assert.equal(shape.unresolved.length, 0, JSON.stringify(shape.unresolved));
  near(shape.ink.bbox.minX, 4, 1e-6);
  near(shape.ink.bbox.maxX, 20, 1e-6);
});

test('a clip-path that cuts the artwork stays unmeasurable', () => {
  const shape = analyzeSvg(
    svg(
      '<defs><clipPath id="c"><rect x="0" y="0" width="10" height="24"/></clipPath></defs>' +
        '<g clip-path="url(#c)"><rect x="4" y="4" width="16" height="16"/></g>',
    ),
  );
  assert.ok(shape.unresolved.includes('clip-path-cuts-ink'), JSON.stringify(shape.unresolved));
  const report = checkShape(shape, { mode: 'standalone', target: 'cut.svg' });
  assert.equal(report.verdict, 'unknown');
});

test('an unresolvable clip shape is refused, not approximated', () => {
  const cases = [
    '<clipPath id="c"><circle cx="12" cy="12" r="12"/></clipPath>',
    '<clipPath id="c"><rect x="0" y="0" width="24" height="24" rx="4"/></clipPath>',
    '<clipPath id="c" clipPathUnits="objectBoundingBox"><rect x="0" y="0" width="1" height="1"/></clipPath>',
    '<clipPath id="c"><rect x="0" y="0" width="24" height="24"/><rect x="0" y="0" width="4" height="4"/></clipPath>',
  ];
  for (const clip of cases) {
    const shape = analyzeSvg(svg(`<defs>${clip}</defs><g clip-path="url(#c)"><rect x="4" y="4" width="16" height="16"/></g>`));
    assert.ok(shape.unresolved.includes('clip-path'), `${clip} -> ${JSON.stringify(shape.unresolved)}`);
  }
});

test('a shape that clips itself is not walked as a container', () => {
  const shape = analyzeSvg(
    svg(
      '<defs><clipPath id="c"><rect x="0" y="0" width="24" height="24"/></clipPath></defs>' +
        '<rect clip-path="url(#c)" x="4" y="4" width="16" height="16"/>',
    ),
  );
  assert.ok(shape.unresolved.includes('clip-path'), JSON.stringify(shape.unresolved));
});

test('an at-rule nested inside a rule belongs to the parent selector', () => {
  const css = '.btn{display:flex;@media (min-width:600px){text-box:trim-both}}';
  const report = checkCss(css, { target: 'nestcss.css' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'off');
  // The evidence must name the real selector, not a phantom ".btn @media …".
  assert.match(f.evidence, /^\.btn:/);
  assert.match(f.evidence, /min-width/);
});

test('declarations before and after a nested rule keep their source order', () => {
  const before = checkCss('.a{text-box:trim-both;@media (x){color:red}}', { target: 'b.css' });
  assert.equal(before.findings.length, 1, JSON.stringify(before.findings, null, 2));

  // Declarations *after* the nested block must still be seen, and must win.
  const after = checkCss('.b{@media (x){color:red}text-box-trim:none}', { target: 'a.css' });
  assert.equal(after.findings.length, 0, JSON.stringify(after.findings, null, 2));
});

test('a nested selector is still a different element', () => {
  const css = '.btn{display:flex;@media (x){& span{text-box:trim-both}}}';
  const report = checkCss(css, { target: 'child.css' });
  // The span is not the flex container; `.btn`'s display must not be borrowed.
  assert.equal(
    report.findings.filter((f) => f.evidence.startsWith('.btn:')).length,
    0,
    JSON.stringify(report.findings, null, 2),
  );
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  // No display for `.btn span` itself -> the container type is unknown, not off.
  assert.equal(f.verdict, 'unknown');
  assert.match(f.evidence, /\.btn span/);
});

test('a clip on <use>/<svg> is evaluated against the instantiated content', () => {
  const clip = (id, w) =>
    `<defs><clipPath id="${id}"><rect x="0" y="0" width="${w}" height="24"/></clipPath></defs>`;
  const symbol = '<symbol id="s"><rect x="4" y="4" width="16" height="16"/></symbol>';
  const nested =
    '<svg width="12" height="12" viewBox="0 0 12 12"><rect x="0" y="0" width="12" height="12"/></svg>';

  // A clip that covers everything must not change the conclusion.
  const okSymbol = analyzeSvg(svg(`${clip('c', 24)}${symbol}<use href="#s" clip-path="url(#c)"/>`));
  assert.deepEqual(okSymbol.unresolved, []);
  near(okSymbol.ink.bbox.minX, 4, 1e-6);
  near(okSymbol.ink.bbox.maxX, 20, 1e-6);

  const okSvg = analyzeSvg(svg(`${clip('c', 24)}${nested.replace('<svg ', '<svg clip-path="url(#c)" ')}`));
  assert.deepEqual(okSvg.unresolved, []);
  near(okSvg.ink.bbox.maxX, 12, 1e-6);

  // A clip that would remove ink is unmeasurable, not empty.
  const cutSymbol = analyzeSvg(svg(`${clip('d', 10)}${symbol}<use href="#s" clip-path="url(#d)"/>`));
  assert.ok(cutSymbol.unresolved.includes('clip-path-cuts-ink'), JSON.stringify(cutSymbol.unresolved));

  const cutSvg = analyzeSvg(
    svg(`${clip('d', 10)}${nested.replace('<svg ', '<svg clip-path="url(#d)" ')}`),
  );
  assert.ok(cutSvg.unresolved.includes('clip-path-cuts-ink'), JSON.stringify(cutSvg.unresolved));
});

test('a no-op clip never changes the verdict for a container', () => {
  const plain = checkShape(analyzeSvg(svg('<g><rect x="4" y="4" width="16" height="16"/></g>')), {
    target: 'a.svg',
  });
  const clipped = checkShape(
    analyzeSvg(
      svg(
        '<defs><clipPath id="c"><rect x="0" y="0" width="24" height="24"/></clipPath></defs>' +
          '<g clip-path="url(#c)"><rect x="4" y="4" width="16" height="16"/></g>',
      ),
    ),
    { target: 'b.svg' },
  );
  assert.equal(clipped.verdict, plain.verdict);
  near(clipped.findings[0].measured.dx, plain.findings[0].measured.dx, 1e-9);
});

test('fill-opacity is inherited, opacity is not', () => {
  const invisible = analyzeSvg(
    svg('<g fill-opacity="0"><rect x="4" y="4" width="16" height="16"/></g>'),
  );
  assert.equal(invisible.noInk, true);

  const visible = analyzeSvg(
    svg('<g fill-opacity="0.4"><rect x="4" y="4" width="16" height="16"/></g>'),
  );
  assert.equal(visible.noInk, false);
  // opacity composites the whole group, so a semi-transparent group is still ink
  const group = analyzeSvg(svg('<g opacity="0.5"><rect x="4" y="4" width="16" height="16"/></g>'));
  assert.equal(group.noInk, false);
});

// --- round 5: one pipeline for scopes, honest units --------------------------

test('<use> into an <svg viewBox> applies the viewBox exactly once', () => {
  const shape = analyzeSvg(
    svg(
      '<defs><svg id="s" viewBox="0 0 10 10"><rect width="10" height="10"/></svg></defs>' +
        '<use href="#s"/>',
    ),
  );
  // 10 units scaled 2.4 into the 24-unit viewport: 0..24, not 0..57.6.
  near(shape.ink.bbox.maxX, 24, 1e-6);
  near(shape.ink.bbox.maxY, 24, 1e-6);
});

test('ink we can see but cannot measure is unresolved, not empty', () => {
  for (const body of [
    '<text x="2" y="2">hi</text>',
    '<image x="0" y="0" width="10" height="10" href="a.png"/>',
    '<foreignObject width="10" height="10"><div/></foreignObject>',
  ]) {
    const shape = analyzeSvg(svg(body));
    assert.ok(
      shape.unresolved.some((u) => u.startsWith('unsupported-ink:')),
      `${body} -> ${JSON.stringify(shape.unresolved)}`,
    );
  }
});

test('a transform on the root <svg> is not part of the artwork', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" transform="translate(100,100)">' +
      '<rect x="4" y="4" width="16" height="16"/></svg>',
  );
  near(shape.ink.bbox.minX, 4, 1e-6);
  near(shape.ink.bbox.maxX, 20, 1e-6);
});

test('preserveAspectRatio="none" scales each axis separately', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="48" height="24" preserveAspectRatio="none">' +
      '<rect x="0" y="0" width="4" height="4"/></svg>',
  );
  near(shape.unitScaleX, 2, 1e-9);
  near(shape.unitScaleY, 1, 1e-9);
  assert.equal(shape.unitScale, null);
  assert.equal(shape.unitSource, 'declared');

  const report = checkShape(shape, { target: 'stretch.svg' });
  const f = report.findings.find((x) => x.id === 'geometry/ink-bbox');
  // ink centre (2,2) vs viewBox centre (12,12): -10 units -> -20px / -10px.
  near(f.measured.dx, -20, 1e-6);
  near(f.measured.dy, -10, 1e-6);
});

test('preserveAspectRatio="slice" scales by the larger ratio', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="48" height="24" preserveAspectRatio="xMidYMid slice">' +
      '<rect x="0" y="0" width="4" height="4"/></svg>',
  );
  near(shape.unitScaleX, 2, 1e-9);
  near(shape.unitScaleY, 2, 1e-9);
});

test('a transform with an unresolvable argument is refused, not truncated', () => {
  // Dropping "10%" would turn translate(10%,8) into translate(8,0).
  const shape = analyzeSvg(svg('<g transform="translate(10%,8)"><rect x="0" y="0" width="4" height="4"/></g>'));
  assert.ok(shape.unresolved.includes('unparsed-transform'), JSON.stringify(shape.unresolved));

  const bad = analyzeSvg(svg('<g transform="skewX(2em)"><rect x="0" y="0" width="4" height="4"/></g>'));
  assert.ok(bad.unresolved.includes('unparsed-transform'), JSON.stringify(bad.unresolved));
});

test('a percentage stroke-width is not read as user units', () => {
  const shape = analyzeSvg(
    svg('<rect x="4" y="4" width="16" height="16" stroke="#000" stroke-width="10%"/>'),
  );
  assert.ok(shape.unresolved.includes('stroke-width-percentage'), JSON.stringify(shape.unresolved));
});

test('conflicting trim declarations across @layer are unknown, not last-wins', () => {
  const css =
    '@layer base, overrides;' +
    '@layer base { .x { text-box-trim: trim-both } }' +
    '@layer overrides { .x { text-box-trim: none } }';
  const report = checkCss(css, { target: 'layer.css' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.equal(f.verdict, 'unknown');
  assert.match(f.evidence, /cascade order/);
});

test('tailwind variant prefixes do not hide the display decision', () => {
  for (const cls of ['text-box-trim md:flex', 'hidden md:flex text-box-trim', 'text-box-trim dark:hover:grid']) {
    const report = checkTsx(`<div className="${cls}" />`, { target: 'variant.tsx' });
    const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
    assert.ok(f, `${cls}: ${JSON.stringify(report.findings, null, 2)}`);
    assert.equal(f.verdict, 'off', cls);
  }
});

test('a non-flex display utility is a pass, not a gap', () => {
  for (const cls of ['text-box-trim block', 'text-box-trim sr-only', 'text-box-trim inline-block']) {
    const report = checkTsx(`<div className="${cls}" />`, { target: 'block.tsx' });
    assert.equal(report.findings.length, 0, `${cls}: ${JSON.stringify(report.findings, null, 2)}`);
  }
});

test('a directory does not silently answer a standalone question', () => {
  const r = run('check', fixture('icons/set'), '--mode', 'standalone');
  assert.equal(r.status, 64, r.stderr);
  assert.match(r.stderr, /directory/);
});

test('a self-referencing <symbol> terminates instead of overflowing the stack', () => {
  const shape = analyzeSvg(
    svg('<symbol id="a"><use href="#a"/></symbol><use href="#a"/>'),
  );
  assert.ok(shape.unresolved.includes('use-nested-too-deep'), JSON.stringify(shape.unresolved));
});

test('a clip on a viewport element must contain the ink under both readings', () => {
  // The clip rect is authored in the outer space (0..24). Read in the inner
  // space of a 10-unit viewBox scaled 2.4x it would cover 0..57.6, so a naive
  // single-reading check could pass a clip that actually cuts.
  const body =
    '<defs><clipPath id="c"><rect x="0" y="0" width="10" height="10"/></clipPath></defs>' +
    '<svg clip-path="url(#c)" width="24" height="24" viewBox="0 0 10 10">' +
    '<rect x="0" y="0" width="10" height="10"/></svg>';
  const shape = analyzeSvg(svg(body));
  assert.ok(shape.unresolved.includes('clip-path-cuts-ink'), JSON.stringify(shape.unresolved));
});

test('a display conflict that stays flexy is still a defect', () => {
  const css =
    '.c{display:flex;text-box:trim-both}@media (min-width:600px){.c{display:inline-flex}}';
  const report = checkCss(css, { target: 'flexy.css' });
  const f = report.findings.find((x) => x.id === 'rule/text-box-in-flex');
  // Both branches are flex containers, so there is no ambiguity to report.
  assert.equal(f.verdict, 'off');
});

test('variant stripping survives nested brackets', () => {
  const cases = [
    ['supports-[display:grid]:flex', 'flex'],
    ['[&>*]:flex', 'flex'],
    ['data-[state=open]:grid', 'grid'],
    ['dark:hover:md:flex', 'flex'],
    ['md:[@media(min-width:900px)]:flex', 'flex'],
  ];
  for (const [token, stem] of cases) {
    assert.deepEqual(classInfo(`"${token}"`).stems, [stem], token);
  }
});

test('verdicts are comparable across icon grids', () => {
  // Same 8% imbalance drawn on a 24-unit and a 480-unit canvas must read the same.
  const small = analyzeSvg(svg('<rect x="0" y="0" width="20" height="20"/>'));
  const large = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 480">' +
      '<rect x="0" y="0" width="400" height="400"/></svg>',
  );
  near(small.unitScale, 1, 1e-9);
  near(large.unitScale, 0.05, 1e-9);
  const a = checkShape(small, { target: 's.svg' }).findings.find((f) => f.id === 'geometry/ink-bbox');
  const b = checkShape(large, { target: 'l.svg' }).findings.find((f) => f.id === 'geometry/ink-bbox');
  assert.equal(a.verdict, b.verdict, `${a.verdict} vs ${b.verdict}`);
  near(a.relative.dx_pct, b.relative.dx_pct, 1e-9);
});

test('a px suggestion is not the number to add to the origin', () => {
  // The viewBox origin is in user units; `value` is in px. On a non-1:1 grid the
  // two differ, so `delta` has to be published or the advice is unusable.
  const report = checkShape(
    analyzeSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 480">' +
        '<rect x="0" y="0" width="440" height="480"/></svg>',
    ),
    { target: 'wide.svg' },
  );
  const bbox = report.findings.find((f) => f.id === 'geometry/ink-bbox');
  near(bbox.measured.dx, -20 * 0.05, 1e-6); // 20 user units left of centre, at 0.05 px/unit
  assert.ok(bbox.suggested.delta, `missing delta: ${JSON.stringify(bbox.suggested)}`);
  const [dx] = bbox.suggested.delta.split('/').map((s) => Number(s));
  near(dx, -20, 1e-6);
  const originX = Number(bbox.suggested.viewBox.split(' ')[0]);
  near(originX, -20, 1e-6);
  // The attribute and the delta agree; `value` deliberately does not.
  assert.match(bbox.suggested.value, /^-1px \/ 0px$/);
});

test('a 1:1 icon gets no delta field, because value already is the delta', () => {
  const report = checkShape(analyzeSvg(svg('<rect x="0" y="0" width="20" height="24"/>')), {
    target: 'square.svg',
  });
  const bbox = report.findings.find((f) => f.id === 'geometry/ink-bbox');
  assert.equal(bbox.suggested.delta, undefined);
  assert.match(bbox.suggested.value, /^-2px \/ 0px$/);
  assert.match(bbox.suggested.viewBox, /^-2 0 24 24$/);
});

// --- paint that lives in a stylesheet ---------------------------------------

test('paint declared in <style> is resolved, not ignored', () => {
  // The background rect is invisible in the browser. Measuring it as solid ink
  // put the drawn cross in the corner of a canvas that was full of paint.
  const styled = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.bg{fill:none}</style>' +
      '<rect class="bg" width="24" height="24"/>' +
      '<rect x="14" y="8" width="8" height="8"/></svg>',
  );
  const inline = analyzeSvg(
    svg('<rect fill="none" width="24" height="24"/><rect x="14" y="8" width="8" height="8"/>'),
  );
  for (const shape of [styled, inline]) {
    assert.deepEqual(shape.unresolved, []);
    near(shape.ink.bbox.minX, 14);
    near(shape.ink.bbox.minY, 8);
  }
  assert.equal(
    checkShape(styled, { target: 's.svg' }).verdict,
    checkShape(inline, { target: 'i.svg' }).verdict,
  );
});

test('a stylesheet rule outranks a presentation attribute', () => {
  // Cascade, not precedence by eye: `fill="black"` on the element loses to
  // `.x{fill:none}` in the sheet.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.x{fill:none}</style>' +
      '<rect class="x" fill="#000" width="24" height="24"/>' +
      '<rect x="14" y="8" width="8" height="8"/></svg>',
  );
  near(shape.ink.bbox.minX, 14);
});

test('inline style still beats the stylesheet', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.x{fill:none}</style>' +
      '<rect class="x" style="fill:#000" width="24" height="24"/>' +
      '<rect x="14" y="8" width="8" height="8"/></svg>',
  );
  near(shape.ink.bbox.minX, 0);
});

test('a stylesheet this pass cannot evaluate is refused, not approximated', () => {
  const descendantShape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>g rect{fill:none}</style><g><rect width="24" height="24"/></g>' +
      '<rect x="14" y="8" width="8" height="8"/></svg>',
  );
  assert.match(descendantShape.unresolved.join(), /stylesheet-selector/);
  assert.equal(checkShape(descendantShape, { target: 'd.svg' }).verdict, 'unknown');

  const conditionalShape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>@media (prefers-color-scheme: dark){.bg{fill:none}}</style>' +
      '<rect class="bg" width="24" height="24"/><rect x="14" y="8" width="8" height="8"/></svg>',
  );
  assert.match(conditionalShape.unresolved.join(), /stylesheet-conditional/);
  assert.equal(checkShape(conditionalShape, { target: 'm.svg' }).verdict, 'unknown');
});

// --- lengths that are not user units ----------------------------------------

test('percentage geometry is refused instead of read as units', () => {
  // `parseFloat("100%")` is 100 — a background rect becomes ink at 100,100 and a
  // perfectly centred icon reports +38px.
  const percent = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<rect x="25%" y="25%" width="50%" height="50%"/></svg>',
  );
  const report = checkShape(percent, { target: 'p.svg' });
  assert.equal(report.verdict, 'unknown');
  assert.match(percent.unresolved.join(), /unparsed-length/);
});

test('a percentage clip rect is refused, in both directions', () => {
  const clip = (inkX) =>
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
    '<clipPath id="c"><rect x="10%" width="80%" height="100%"/></clipPath>' +
    `<g clip-path="url(#c)"><rect x="${inkX}" y="8" width="8" height="8"/></g></svg>`;
  for (const x of [8, 16]) {
    const report = checkShape(analyzeSvg(clip(x)), { target: 'c.svg' });
    assert.equal(report.verdict, 'unknown', `ink at ${x}`);
  }
});

test('a percentage stroke-width is refused on ancestors too', () => {
  // `stroke-width` inherits; only checking the shape itself let a <g> smuggle a
  // percentage through as plain units.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<g fill="none" stroke="#000" stroke-width="10%"><path d="M6 12 H18"/></g></svg>',
  );
  assert.match(shape.unresolved.join(), /stroke-width-percentage/);
  assert.equal(checkShape(shape, { target: 'g.svg' }).verdict, 'unknown');
});

test('a viewBox with surrounding whitespace still parses', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox=" 0 0 512 512">' +
      '<rect x="56" y="56" width="400" height="400"/></svg>',
  );
  assert.deepEqual(shape.viewBox, { x: 0, y: 0, w: 512, h: 512 });
  near(shape.unitScale, 24 / 512, 1e-9);
  assert.equal(checkShape(shape, { target: 'w.svg' }).verdict, 'ok');
});

test('a malformed viewBox is refused rather than replaced by 24x24', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 abc 24">' +
      '<rect x="0" y="0" width="20" height="24"/></svg>',
  );
  assert.equal(shape.noInk, true);
  assert.match(shape.unresolved.join(), /invalid-viewBox/);
  const report = checkShape(shape, { target: 'bad.svg' });
  assert.equal(report.verdict, 'unknown');
  // The reason is the canvas, not "maybe it is empty" — do not report both.
  assert.deepEqual(
    report.findings.map((f) => f.id),
    ['geometry/unresolved-graphics'],
  );
});

test('physical units are absolute, not a reason to assume 24px', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="1in" height="1in">' +
      '<rect x="0" y="0" width="24" height="24"/></svg>',
  );
  near(shape.unitScale, 96 / 24, 1e-9);
  assert.equal(shape.unitSource, 'declared');
});

test('preserveAspectRatio="none" has no single scale, even when assumed', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" preserveAspectRatio="none">' +
      '<rect x="0" y="0" width="24" height="24"/></svg>',
  );
  assert.equal(shape.unitScale, null);
  near(shape.unitScaleX, 1, 1e-9);
});

// --- paint declared on <symbol> --------------------------------------------

test('a <symbol> hands its own paint to the instance', () => {
  // Sprite sets put `fill`/`stroke`/`fill-rule` on the symbol so children can
  // omit them. Ignoring that changed the area of every referenced path.
  const symbol = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<symbol id="s" fill-rule="evenodd">' +
      '<path d="M4 4 H20 V20 H4 Z M8 8 H20 V20 H8 Z"/></symbol>' +
      '<use href="#s"/></svg>',
  );
  const inline = analyzeSvg(
    svg('<path fill-rule="evenodd" d="M4 4 H20 V20 H4 Z M8 8 H20 V20 H8 Z"/>'),
  );
  near(symbol.ink.area, inline.ink.area, 1e-6);
  near(symbol.ink.centroid.cx, inline.ink.centroid.cx, 1e-6);

  const stroked = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<symbol id="s" fill="none" stroke="#000" stroke-width="2">' +
      '<path d="M6 12 H18"/></symbol><use href="#s"/></svg>',
  );
  assert.equal(checkShape(stroked, { target: 's.svg' }).verdict, 'ok');
});

// --- shape bookkeeping -----------------------------------------------------

test('overlapping subpaths are refused instead of double-counted', () => {
  const duplicate = analyzeSvg(
    svg('<path fill-rule="evenodd" d="M4 4 H20 V20 H4 Z M4 4 H20 V20 H4 Z"/>'),
  );
  assert.match(duplicate.unresolved.join(), /overlapping-subpaths/);
  // A genuine hole is still measured.
  const hole = analyzeSvg(svg('<path fill-rule="evenodd" d="M2 2 H22 V22 H2 Z M6 6 H18 V18 H6 Z"/>'));
  assert.deepEqual(hole.unresolved, []);
  near(hole.ink.area, 20 * 20 - 12 * 12, 1e-6);
});

test('a zero radius is empty ink, not a parse failure', () => {
  const shape = analyzeSvg(svg('<circle cx="12" cy="12" r="0"/>'));
  assert.equal(shape.noInk, true);
  assert.deepEqual(shape.unresolved, []);
});

test('deep nesting is refused before the stack gives out', () => {
  const deep =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
    '<g>'.repeat(6000) +
    '<rect x="0" y="0" width="20" height="24"/>' +
    '</g>'.repeat(6000) +
    '</svg>';
  const shape = analyzeSvg(deep);
  assert.match(shape.unresolved.join(), /nesting-too-deep/);
  assert.equal(checkShape(shape, { target: 'deep.svg' }).verdict, 'unknown');
});

// --- CLI surface -----------------------------------------------------------

test('text output carries the attribute to paste, not just the px number', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-'));
  const file = join(dir, 'big.svg');
  writeFileSync(
    file,
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 480">' +
      '<rect x="0" y="0" width="440" height="480"/></svg>',
  );
  const out = run('check', file);
  assert.match(out.stdout, /paste viewBox="-20 0 480 480"/);
  assert.match(out.stdout, /delta -20 \/ 0/);
});

test('a missing path is a usage error, not a verdict', () => {
  const out = run('check', join(tmpdir(), 'definitely-not-here.svg'));
  assert.equal(out.status, 64);
  assert.match(out.stderr, /no such file/);
});

test('one unreadable path does not take the batch down', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-'));
  const good = join(dir, 'good.svg');
  writeFileSync(good, svg('<rect x="2" y="0" width="20" height="24"/>'));
  // A directory with an .svg name and no icons in it.
  const empty = join(dir, 'empty.svg');
  mkdirSync(empty);
  const out = run('check', good, empty, '--json');
  const reports = JSON.parse(out.stdout);
  assert.equal(reports.length, 2);
  assert.equal(reports[0].verdict, 'ok');
  assert.equal(reports[1].verdict, 'unknown');
  assert.match(reports[1].findings[0].id, /keyline-empty/);
  assert.equal(out.status, 2);
});

// --- cascade, continued ----------------------------------------------------

test('!important attaches to a declaration, not to its block', () => {
  // `.bg` marks only `fill` important; `stroke:#000` stays normal, so `#bg`'s
  // `stroke:none` still wins. Treating the block as one unit silently painted a
  // 24x24 background and turned a certain `off` into `ok`.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><style>' +
      '.bg{fill:none !important; stroke:#000} #bg{stroke:none}' +
      '</style><rect id="bg" class="bg" width="24" height="24"/>' +
      '<rect x="2" y="2" width="2" height="2"/></svg>',
  );
  near(shape.ink.area, 4, 1e-6);
  assert.equal(checkShape(shape, { target: 'leak.svg' }).verdict, 'off');
});

test('inline !important outranks a stylesheet rule', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.x{fill:#000}</style>' +
      '<rect class="x" style="fill:none !important" width="24" height="24"/>' +
      '<rect x="14" y="8" width="8" height="8"/></svg>',
  );
  near(shape.ink.bbox.minX, 14);
});

test('a stylesheet !important outranks plain inline style', () => {
  // The order is sheet-normal < inline-normal < sheet-important <
  // inline-important. Applying inline last unconditionally gets this wrong.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.x{fill:none !important}</style>' +
      '<rect class="x" style="fill:#000" width="24" height="24"/>' +
      '<rect x="14" y="8" width="8" height="8"/></svg>',
  );
  near(shape.ink.bbox.minX, 14);
});

test('a commented-out <style> is documentation, not paint', () => {
  const commented = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<!-- <style>.bg{fill:none}</style> -->' +
      '<rect class="bg" width="24" height="24"/>' +
      '<rect x="14" y="8" width="8" height="8"/></svg>',
  );
  const absent = analyzeSvg(
    svg('<rect class="bg" width="24" height="24"/><rect x="14" y="8" width="8" height="8"/>'),
  );
  near(commented.ink.area, absent.ink.area, 1e-6);
  near(commented.ink.centroid.cx, absent.ink.centroid.cx, 1e-6);
});

test('a stray brace does not truncate the rest of the sheet', () => {
  const clean = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.a{fill:#000} .a{fill:none}</style>' +
      '<rect class="a" width="24" height="24"/><rect x="14" y="8" width="8" height="8"/></svg>',
  );
  const stray = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.a{fill:#000}} .a{fill:none}</style>' +
      '<rect class="a" width="24" height="24"/><rect x="14" y="8" width="8" height="8"/></svg>',
  );
  near(stray.ink.area, clean.ink.area, 1e-6);
  assert.deepEqual(stray.unresolved, []);
});

test('a compound selector of tag and id is evaluated, not refused', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>rect#bg{fill:none}</style>' +
      '<rect id="bg" width="24" height="24"/><rect x="14" y="8" width="8" height="8"/></svg>',
  );
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.bbox.minX, 14);
});

// --- more ways a canvas can be unknown --------------------------------------

test('a percentage root width leaves the canvas unknown', () => {
  // `width="100%"` is sized by the host. Falling back to 24x24 invented a canvas
  // and reported an offset against it.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">' +
      '<rect x="0" y="0" width="20" height="20"/></svg>',
  );
  assert.match(shape.unresolved.join(), /relative-canvas/);
  assert.equal(checkShape(shape, { target: 'pct.svg' }).verdict, 'unknown');
});

test('an animated icon is not measured from one frame', () => {
  const spinner = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<g><path d="M12 3 A9 9 0 0 1 21 12" fill="none" stroke="#000" stroke-width="2"/>' +
      '<animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite"/>' +
      '</g></svg>',
  );
  assert.match(spinner.unresolved.join(), /animated-ink/);

  // A colour cycle moves no ink, so the geometry still stands.
  const pulse = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<rect x="2" y="0" width="20" height="24" fill="#000">' +
      '<animate attributeName="fill" from="#000" to="#f00" dur="1s"/></rect></svg>',
  );
  assert.deepEqual(pulse.unresolved, []);
});

test('ink the viewport would clip is refused', () => {
  const symbol = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<symbol id="s"><rect x="-40" y="-40" width="100" height="100"/></symbol>' +
      '<use href="#s"/></svg>',
  );
  assert.match(symbol.unresolved.join(), /ink-outside-viewport/);

  const inside = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<symbol id="s"><rect x="4" y="4" width="16" height="16"/></symbol>' +
      '<use href="#s"/></svg>',
  );
  assert.deepEqual(inside.unresolved, []);
});

test('a hidden symbol contributes no ink', () => {
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<symbol id="s" visibility="hidden"><rect width="24" height="24"/></symbol>' +
      '<use href="#s"/><rect x="14" y="8" width="8" height="8"/></svg>',
  );
  near(shape.ink.bbox.minX, 14);
});

// --- smaller corrections ----------------------------------------------------

test('disjoint subpaths never cancel, whatever their winding', () => {
  // Both regions have winding 1 on their own, so an opposite direction is not a
  // hole. The signed sum removed one of them and dragged the centroid.
  const shape = analyzeSvg(
    svg('<path d="M0 0 H10 V10 H0 Z M20 0 V10 H30 V0 Z"/>'),
  );
  near(shape.ink.area, 200, 1e-6);
  near(shape.ink.centroid.cx, 15, 1e-6);
});

test('an empty path is empty, not unparseable', () => {
  const shape = analyzeSvg(svg('<path d="" /><rect x="2" y="0" width="20" height="24"/>'));
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.area, 480, 1e-6);
});

test('CSS keywords are case-insensitive', () => {
  const shape = analyzeSvg(
    svg('<rect fill="None" width="24" height="24"/><rect x="14" y="8" width="8" height="8"/>'),
  );
  near(shape.ink.bbox.minX, 14);
});

test('trailing junk invalidates the whole transform list', () => {
  // `translate(10,10) garbage` is not a translation. Splicing it out moved the
  // artwork 10 units and said nothing.
  const shape = analyzeSvg(
    svg('<g transform="translate(10,10) garbage"><rect x="0" y="0" width="2" height="2"/></g>'),
  );
  assert.match(shape.unresolved.join(), /unparsed-transform/);
});

test('a directory with an unreadable icon reports unknown, never ok', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-'));
  writeFileSync(join(dir, 'a.svg'), svg('<rect x="2" y="0" width="20" height="24"/>'));
  // A directory whose name ends in .svg makes readFile fail inside the set.
  mkdirSync(join(dir, 'b.svg'));
  const out = run('check', dir, '--json');
  const report = JSON.parse(out.stdout);
  assert.equal(report.verdict, 'unknown');
  assert.equal(out.status, 2);
});

test('a partially parsed path is refused, not measured in halves', () => {
  // svgpath reports `M0 0 L` as "missed param" and still hands back one point.
  // Measuring that fragment would move the ink box to a place the drawing is not.
  for (const d of ['M0 0 L', 'garbage']) {
    const shape = analyzeSvg(svg(`<path d="${d}"/><rect x="2" y="0" width="20" height="24"/>`));
    assert.match(shape.unresolved.join(), /unparsed-path/, d);
    assert.equal(checkShape(shape, { target: 'p.svg' }).verdict, 'unknown', d);
  }
});
