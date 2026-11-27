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

test('a clip on a viewport element is read in the space its viewBox establishes', () => {
  // 10 clip units over a 10-unit viewBox scaled 2.4x covers the whole drawing.
  // Read in the outer space it would cover only 10 of 24 units and look like a
  // cut — headless Chrome draws all 24, so the inner space is the real one.
  const body =
    '<defs><clipPath id="c"><rect x="0" y="0" width="10" height="10"/></clipPath></defs>' +
    '<svg clip-path="url(#c)" width="24" height="24" viewBox="0 0 10 10">' +
    '<rect x="0" y="0" width="10" height="10"/></svg>';
  const shape = analyzeSvg(svg(body));
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.area, 576, 1e-6);
});

test('a symbol and a nested <svg> of one drawing get one verdict', () => {
  // Same pixels, two spellings. They must not disagree — that is the whole
  // point of resolving clip in the space the element actually uses.
  const clip = '<clipPath id="c"><rect width="10" height="10"/></clipPath>';
  const symbol = analyzeSvg(
    svg(
      `${clip}<symbol id="s" viewBox="0 0 10 10" clip-path="url(#c)">` +
        '<rect width="10" height="10"/></symbol><use href="#s" width="24" height="24"/>',
    ),
  );
  const nested = analyzeSvg(
    svg(
      `${clip}<svg viewBox="0 0 10 10" width="24" height="24" clip-path="url(#c)">` +
        '<rect width="10" height="10"/></svg>',
    ),
  );
  assert.deepEqual(symbol.unresolved, []);
  assert.deepEqual(nested.unresolved, []);
  near(symbol.ink.area, nested.ink.area, 1e-6);
  near(symbol.ink.centroid.cx, nested.ink.centroid.cx, 1e-6);
  near(symbol.ink.centroid.cy, nested.ink.centroid.cy, 1e-6);
});

test("a clip on a <use> is read after the element's own x/y", () => {
  // The referenced 12x12 square lands at 6..18 either way; only the clip moves.
  // Chrome draws it whole when the clip says 0..12 and cuts it to 6x6 when the
  // clip says 6..18, which is `x`/`y` applied to the clip and not to the content.
  const at = (clipRect) =>
    `<defs><clipPath id="c"><rect ${clipRect}/></clipPath><g id="g">` +
    '<rect width="12" height="12"/></g></defs><use href="#g" x="6" y="6" clip-path="url(#c)"/>';
  const whole = analyzeSvg(svg(at('x="0" y="0" width="12" height="12"')));
  assert.deepEqual(whole.unresolved, []);
  near(whole.ink.area, 144, 1e-6);
  near(whole.ink.bbox.minX, 6, 1e-6);

  const cut = analyzeSvg(svg(at('x="6" y="6" width="12" height="12"')));
  assert.ok(cut.unresolved.includes('clip-path-cuts-ink'), JSON.stringify(cut.unresolved));
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

test('trailing junk drops the whole transform list, as a browser does', () => {
  // `translate(10,10) garbage` is not a translation and not a half-translation:
  // the attribute is invalid, so the element is untransformed. Refusing would
  // have been right too, but the browser's answer is knowable — and it is not
  // "shifted by 10".
  const shape = analyzeSvg(
    svg('<g transform="translate(10,10) garbage"><rect x="0" y="0" width="2" height="2"/></g>'),
  );
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.bbox.minX, 0, 1e-9);
  near(shape.ink.bbox.minY, 0, 1e-9);
  // The same for a wrong argument count: `rotate(45 12 12 5)` is not a rotation.
  const rotated = analyzeSvg(
    svg('<g transform="rotate(45 12 12 5)"><rect x="0" y="0" width="2" height="2"/></g>'),
  );
  assert.deepEqual(rotated.unresolved, []);
  near(rotated.ink.bbox.minX, 0, 1e-9);
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

// --- round 8: winding, self-crossing, and paint that is not paint -----------

test('a hole inside a hole inside an island paints once, not twice', () => {
  // Nonzero winding accumulates along the ancestor chain: 0 → +1 → 0 → +1.
  // A rule that only compares against the immediate parent reads the third ring
  // as a hole and reports 176 instead of 240.
  const shape = analyzeSvg(
    svg('<path fill-rule="nonzero" d="M0 0H24V24H0Z M2 2V22H22V2Z M8 8H16V16H8Z"/>'),
  );
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.area, 576 - 400 + 64, 1e-6);
  // All three rings are concentric, so the centroid cannot move.
  near(shape.ink.centroid.cx, 12, 1e-6);
  near(shape.ink.centroid.cy, 12, 1e-6);
});

test('same-winding nesting never subtracts under nonzero', () => {
  // The mirror image of the test above: three rings wound the same way are one
  // solid region, because the winding goes 1 → 2 → 3 and never returns to zero.
  const shape = analyzeSvg(svg('<path fill-rule="nonzero" d="M0 0H24V24H0Z M2 2H22V22H2Z M8 8H16V16H8Z"/>'));
  near(shape.ink.area, 576, 1e-6);
});

test('a subpath that crosses itself is refused, not measured as zero', () => {
  // Shoelace gives 0 for a bowtie while it paints two triangles: dropping it as
  // "no area" loses ink with no warning, and the rest of the canvas still looks
  // fine.
  const bowtie = analyzeSvg(svg('<path d="M2 2 L22 22 L22 2 L2 22 Z"/>'));
  assert.match(bowtie.unresolved.join(), /self-intersecting/);
  const report = checkShape(bowtie, { target: 'bowtie.svg' });
  assert.equal(report.verdict, 'unknown');

  // Even-odd has the same blind spot and must refuse the same outline.
  const evenodd = analyzeSvg(svg('<path fill-rule="evenodd" d="M2 2 L22 22 L22 2 L2 22 Z"/>'));
  assert.match(evenodd.unresolved.join(), /self-intersecting/);
});

test('a negligible self-crossing does not disqualify real artwork', () => {
  // Exporters emit sharp corners as a 0.04-unit doubling-back. Its area is one
  // part in 10^8 of the drawing, so refusing it would throw away the file.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 346 346">' +
      '<path d="M20 20h300v300h-300zm6 6h288v288h-288z"/>' +
      '</svg>',
  );
  assert.deepEqual(shape.unresolved, []);
});

test('fill="transparent" is a declaration of no ink', () => {
  for (const paint of ['transparent', '#00000000', 'rgba(0,0,0,0)', 'hsl(0 0% 0% / 0%)']) {
    const shape = analyzeSvg(svg(`<rect width="24" height="24" fill="${paint}"/>`));
    assert.equal(shape.noInk, true, paint);
  }
  // The same on the stroke side: an invisible stroke is not a hairline.
  const stroked = analyzeSvg(svg('<rect width="24" height="24" fill="none" stroke="transparent"/>'));
  assert.equal(stroked.noInk, true);
});

test('a drawing far from the origin keeps its exact area', () => {
  // Shoelace is a difference of products. At x ≈ 1e9 those products reach 1e18,
  // where one float64 step is larger than the shape itself: a 10×10 square read
  // 128 and the centroid drifted out of its own ink box.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="1000000000 1000000000 24 24">' +
      '<rect x="1000000000" y="1000000000" width="10" height="10"/></svg>',
  );
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.area, 100, 1e-6);
  near(shape.ink.centroid.cx, 1000000005, 1e-6);
  near(shape.ink.centroid.cy, 1000000005, 1e-6);
});

test('a stroke that draws nothing is not a hairline', () => {
  // `stroke-width: 0` and `stroke-opacity: 0` both paint nothing. Counting the
  // band anyway gives the drawing a centroid it does not have — a `ok` on an
  // empty canvas, which is the one verdict that must never be invented.
  const nothing = [
    'stroke-width="0"',
    'style="stroke-width:0"',
    'stroke-opacity="0"',
    'stroke-opacity="0%"',
  ];
  for (const attr of nothing) {
    const shape = analyzeSvg(
      svg(`<rect x="2" y="2" width="20" height="20" fill="none" stroke="#000" ${attr}/>`),
    );
    assert.equal(shape.noInk, true, attr);
  }
  // Inherited, not just local.
  const group = analyzeSvg(
    svg('<g stroke-opacity="0"><rect width="24" height="24" fill="none" stroke="#000" stroke-width="2"/></g>'),
  );
  assert.equal(group.noInk, true);

  // A translucent stroke is still ink: the band is there, only fainter.
  const faint = analyzeSvg(
    svg('<rect width="24" height="24" fill="none" stroke="#000" stroke-width="2" stroke-opacity="0.5"/>'),
  );
  near(faint.ink.area, 24 * 4 * 2, 1e-6);

  // A negative width is an invalid declaration — the browser drops it and the
  // element inherits 1 rather than drawing 4 units of band backwards.
  const negative = analyzeSvg(
    svg('<rect width="24" height="24" fill="none" stroke="#000" stroke-width="-4"/>'),
  );
  near(negative.ink.area, 24 * 4 * 1, 1e-6);
});

test('two lobes meeting at a vertex are refused only when they subtract', () => {
  // No crossing anywhere: the triangles touch at (12,12). Shoelace still walks
  // them in order, so opposite winding subtracts one from the other — 50 − 10
  // = 40 where the render paints 60.
  const mixed = analyzeSvg(
    svg('<path d="M12 12 L4 2 L2 12 L12 12 L16 8 L17 12 Z"/>'),
  );
  assert.ok(mixed.unresolved.includes('self-intersecting'), JSON.stringify(mixed.unresolved));

  // The fill rule does not change the geometry of the lie.
  const evenOdd = analyzeSvg(
    svg('<path d="M12 12 L4 2 L2 12 L12 12 L16 8 L17 12 Z" fill-rule="evenodd"/>'),
  );
  assert.ok(evenOdd.unresolved.includes('self-intersecting'), JSON.stringify(evenOdd.unresolved));

  // Wound the same way the lobes add up and the shoelace total is the painted
  // area. Refusing this would be the over-correction that blinds a real icon.
  const same = analyzeSvg(
    svg('<path d="M12 12 L4 2 L2 12 L12 12 L17 12 L16 8 Z"/>'),
  );
  assert.deepEqual(same.unresolved, []);
  near(same.ink.area, 60, 1e-6);
});

test('a mask, a filter or a marker hung on a class still counts', () => {
  // These used to be dropped between the sheet and the node, so the element
  // looked unmasked and came back `ok` on ink nobody could measure.
  const cases = [
    ['mask', '.a{mask:url(#k)}', '<defs><mask id="k"></mask></defs>'],
    ['filter', '.b{filter:blur(2px)}', ''],
    ['marker-end', '.c{marker-end:url(#a)}', ''],
  ];
  for (const [prop, rule, defs] of cases) {
    const cls = /^\.(\w+)/.exec(rule)[1];
    const shape = analyzeSvg(
      svg(`${defs}<style>${rule}</style><path class="${cls}" d="M2 12 H22" stroke="#000"/>`),
    );
    assert.ok(
      shape.unresolved.some((u) => u.startsWith(prop)),
      `${prop}: ${JSON.stringify(shape.unresolved)}`,
    );
  }
});

test('a paint server that does not exist paints nothing', () => {
  // SVG says an invalid paint reference leaves the element unrendered, so the
  // shape is not ink — counting it invented a 20×20 region.
  const missing = analyzeSvg(svg('<rect x="2" y="2" width="20" height="20" fill="url(#nope)"/>'));
  assert.equal(missing.noInk, true);

  // A reference to a real gradient or pattern paints the same region; only the
  // colour changes, and colour is not part of the measurement.
  const gradient = analyzeSvg(
    svg(
      '<defs><linearGradient id="g"><stop offset="0" stop-color="#000"/></linearGradient></defs>' +
        '<rect x="2" y="2" width="20" height="20" fill="url(#g)"/>',
    ),
  );
  near(gradient.ink.area, 400, 1e-6);

  // `url(#g) red` carries a fallback paint, so a broken reference still paints.
  const fallback = analyzeSvg(svg('<rect x="2" y="2" width="20" height="20" fill="url(#nope) red"/>'));
  near(fallback.ink.area, 400, 1e-6);

  // A reference to something that is not a paint server is markup no engine
  // honours — but calling it "no ink" would silently delete ink if the tag were
  // one this pass has not heard of, so it is refused.
  const clip = analyzeSvg(
    svg(
      '<defs><clipPath id="c"><rect width="4" height="4"/></clipPath></defs>' +
        '<rect x="2" y="2" width="20" height="20" fill="url(#c)"/>',
    ),
  );
  assert.ok(clip.unresolved.includes('paint-server'), JSON.stringify(clip.unresolved));
});

test('overflow="visible" lets a nested viewport draw outside itself', () => {
  const clipped = (extra) =>
    analyzeSvg(
      svg(`<svg x="0" y="0" width="10" height="10" viewBox="0 0 10 10" ${extra}>` +
        '<rect width="20" height="20"/></svg>'),
    );
  // Default: the nested viewport is `overflow: hidden`, so the escaping ink is
  // cut off and cannot be measured.
  assert.ok(clipped('').unresolved.includes('ink-outside-viewport'));
  assert.ok(clipped('overflow="hidden"').unresolved.includes('ink-outside-viewport'));
  // `visible` says to draw it anyway, and then it is measurable.
  const open = clipped('overflow="visible"');
  assert.deepEqual(open.unresolved, []);
  near(open.ink.area, 400, 1e-6);
});

test('a marker is ink the path does not describe', () => {
  const shape = analyzeSvg(
    svg('<path d="M2 12 H22" stroke="#000" stroke-width="2" marker-end="url(#arrow)"/>'),
  );
  assert.ok(shape.unresolved.includes('marker-end'), JSON.stringify(shape.unresolved));
  // `none` is the resting value and adds nothing.
  const plain = analyzeSvg(
    svg('<path d="M2 12 H22" stroke="#000" stroke-width="2" marker-end="none"/>'),
  );
  assert.deepEqual(plain.unresolved, []);
});

test('a non-scaling stroke ignores the ancestor scale', () => {
  // The path quadruples, the band does not: perimeter 16 units × scale 4 ×
  // width 1 = 64, not 256.
  const scaled = (effect) =>
    analyzeSvg(
      svg(`<g transform="scale(4)"><rect width="4" height="4" fill="none" stroke="#000" ` +
        `stroke-width="1" ${effect}/></g>`),
    );
  near(scaled('vector-effect="non-scaling-stroke"').ink.area, 64, 1e-6);
  near(scaled('').ink.area, 256, 1e-6);
});

test('a stroke width that overflows to infinity is refused', () => {
  // One engine clamps 1e999 to the largest length and paints a band over the
  // whole canvas; another drops the declaration. Neither is "1 unit".
  const shape = analyzeSvg(svg('<rect width="24" height="24" fill="none" stroke="#000" stroke-width="1e999"/>'));
  assert.ok(shape.unresolved.includes('stroke-width-not-finite'), JSON.stringify(shape.unresolved));
});

test('width/height on a <use> of a plain group is ignored, not refused', () => {
  const shape = analyzeSvg(
    svg(
      '<defs><g id="g"><rect width="12" height="12"/></g></defs>' +
        '<use href="#g" x="6" y="6" width="24" height="24"/>',
    ),
  );
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.area, 144, 1e-6);
});

test('a retraced edge is a hole, not two lobes to subtract', () => {
  // `file-zip` and friends retrace an edge: the inner lobe sits *inside* the
  // outer one, so non-zero fill subtracts it and the shoelace total is right.
  // Refusing these blinded 2 of 8 real icons in one sample.
  const retraced = analyzeSvg(
    svg('<path d="M0 0 H20 V20 H0 L0 0 L0 6 L6 0 Z"/>'),
  );
  assert.deepEqual(retraced.unresolved, []);
  // Chrome renders exactly this much ink for the same path.
  near(retraced.ink.area, 382, 1e-6);
});

test('a hole that meets its container at a corner still subtracts', () => {
  // Every vertex of the hole lies on the container's outline, so the vertex test
  // found no interior point and the hole was counted as a second island: 418
  // where the render paints 382. The centroid is not a vertex and still knows.
  for (const rule of ['nonzero', 'evenodd']) {
    const shape = analyzeSvg(
      svg(`<path d="M0 0 H20 V20 H0 Z M0 0 V6 L6 0 Z" fill-rule="${rule}"/>`),
    );
    assert.deepEqual(shape.unresolved, [], rule);
    near(shape.ink.area, 382, 1e-6);
  }
});

test('a stroke width whose area overflows is refused, not reported as NaN', () => {
  // `1e308` is finite, so the infinity check on the width passed; the band area
  // then overflowed to Infinity and the centroid to NaN, and NaN compares false
  // against every tolerance — the report came back `off` with `cx: NaN`.
  const shape = analyzeSvg(
    svg('<rect width="24" height="24" fill="none" stroke="#000" stroke-width="1e308"/>'),
  );
  assert.ok(shape.unresolved.includes('non-finite-ink'), JSON.stringify(shape.unresolved));
  assert.ok(Number.isFinite(shape.ink.area), `area ${shape.ink.area}`);
});

test('a transform with an empty argument is malformed, not a shorter list', () => {
  // Splitting `translate(10,)` produced one number, so the element moved by 10
  // as if the attribute were well formed.
  for (const t of ['translate(10,)', 'translate(,10)', 'translate(1,,2)']) {
    const shape = analyzeSvg(svg(`<g transform="${t}"><rect width="2" height="2"/></g>`));
    assert.deepEqual(shape.unresolved, [], t);
    near(shape.ink.bbox.minX, 0, 1e-9);
  }
});

test('a fallback paint of none paints nothing', () => {
  // `url(#g) none` is a valid declaration whose fallback resolves to "no paint".
  for (const fallback of ['none', 'transparent']) {
    const shape = analyzeSvg(
      svg(`<rect x="2" y="2" width="20" height="20" fill="url(#missing) ${fallback}"/>`),
    );
    assert.equal(shape.noInk, true, fallback);
  }
  const painted = analyzeSvg(svg('<rect x="2" y="2" width="20" height="20" fill="url(#missing) red"/>'));
  near(painted.ink.area, 400, 1e-6);
});

test('a paint that resolves at runtime is refused, not guessed', () => {
  for (const paint of ['var(--icon-fill)', 'env(safe-area-inset-top, #000)']) {
    const report = checkShape(analyzeSvg(svg(`<rect width="24" height="24" fill="${paint}"/>`)), {
      target: 'var.svg',
    });
    assert.equal(report.verdict, 'unknown', paint);
  }
  // `currentColor` does paint; only its hue is unknown, and hue never moves ink.
  const current = analyzeSvg(svg('<rect width="24" height="24" fill="currentColor"/>'));
  assert.deepEqual(current.unresolved, []);
});

test('!important attaches to the declaration that carries it, not to the property', () => {
  // `.bg` marks only the first `fill` important. Reading the flag per property
  // let the second, normal declaration inherit it and win — restoring the
  // background the sheet had switched off.
  const report = checkShape(
    analyzeSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
        '<style>.bg{fill:none!important;fill:#000}</style>' +
        '<rect class="bg" width="24" height="24"/></svg>',
    ),
    { target: 'imp.svg' },
  );
  assert.equal(report.verdict, 'unknown');
  assert.match(report.findings.map((f) => f.evidence).join(' '), /no renderable ink/);
});

test('@import makes a stylesheet unreadable rather than empty', () => {
  const report = checkShape(
    analyzeSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
        '<style>@import url(theme.css);</style>' +
        '<rect width="24" height="24"/></svg>',
    ),
    { target: 'import.svg' },
  );
  assert.equal(report.verdict, 'unknown');
  assert.match(report.findings.map((f) => f.evidence).join(' '), /stylesheet-unparsed/);
});

test('a CSS animation is not measured from its first frame', () => {
  const animated = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.spin{animation:turn 1s linear infinite}@keyframes turn{to{transform:rotate(360deg)}}</style>' +
      '<rect class="spin" x="2" y="0" width="20" height="24"/></svg>',
  );
  assert.match(animated.unresolved.join(), /css-animation/);
  assert.equal(checkShape(animated, { target: 'spin.svg' }).verdict, 'unknown');

  // `animation: none` leaves the element at rest.
  const still = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<style>.a{animation:none}</style><rect class="a" x="2" y="0" width="20" height="24"/></svg>',
  );
  assert.deepEqual(still.unresolved, []);
});

test('a mask on a symbol is reported, not swallowed by the symbol', () => {
  // `<symbol>` is non-rendering on its own, so `collect` never visits it — but
  // the <use> that instantiates it makes its mask live.
  for (const attr of ['mask="url(#m)"', 'filter="url(#f)"', 'clip-path="url(#c)"']) {
    const shape = analyzeSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
        `<symbol id="s" ${attr}><rect width="24" height="24"/></symbol>` +
        '<use href="#s"/></svg>',
    );
    assert.equal(checkShape(shape, { target: 'sym.svg' }).verdict, 'unknown', attr);
  }
});

test('a rotated viewport is measured across its real corners', () => {
  // The two diagonal corners of a rotated rect lie on the same diagonal, so
  // transforming only those collapses the viewport to a line and every drawing
  // inside it reads as outside.
  const shape = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<g transform="rotate(45 12 12)">' +
      '<symbol id="s" viewBox="0 0 10 10"><rect x="1" y="1" width="8" height="8"/></symbol>' +
      '<use href="#s" x="2" y="2" width="20" height="20"/></g></svg>',
  );
  assert.deepEqual(shape.unresolved, []);
});

test('a zero-sized canvas renders nothing instead of a centred dot', () => {
  for (const side of ['width="0"', 'height="0"']) {
    const shape = analyzeSvg(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ${side}>` +
        '<rect width="24" height="24"/></svg>',
    );
    assert.equal(shape.noInk, true, side);
    assert.match(shape.unresolved.join(), /zero-canvas/, side);
  }
});

test('a comma-separated transform list is parsed, not rejected', () => {
  const shape = analyzeSvg(svg('<rect transform="translate(1px, 1px), scale(1)" x="2" y="0" width="20" height="24"/>'));
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.bbox.minX, 3);
});

test('a clip is read in the space the element actually lives in', () => {
  // Chrome renders `<use x="6" y="6" clip-path="…12×12 at 0,0">` with the clip
  // translated as well: the clip follows the referenced content, it is not the
  // parent's rect. Reading it in the parent's space left a 6-unit strip of the
  // content outside the clip and called a correct file `clip-path-cuts-ink`.
  //
  // The clip here is the *same size* as the content and starts at the origin, so
  // the two readings disagree — a canvas-sized clip would contain the ink either
  // way and test nothing.
  const use = analyzeSvg(
    svg(
      '<clipPath id="c"><rect width="12" height="12"/></clipPath>' +
        '<defs><g id="g"><rect width="12" height="12"/></g></defs>' +
        '<use href="#g" x="6" y="6" clip-path="url(#c)"/>',
    ),
  );
  assert.deepEqual(use.unresolved, []);

  // Ink that really leaves the clip is still refused: a 6×6 clip against 12×12
  // content leaves the far half outside.
  const cut = analyzeSvg(
    svg(
      '<clipPath id="c"><rect width="6" height="6"/></clipPath>' +
        '<defs><g id="g"><rect width="12" height="12"/></g></defs>' +
        '<use href="#g" x="6" y="6" clip-path="url(#c)"/>',
    ),
  );
  assert.match(cut.unresolved.join(), /clip-path-cuts-ink/);

  // A clip on a <symbol> lives in the space the symbol's viewBox establishes.
  // Judging it in the outer space refused every symbol that unit-scales.
  const symbol = analyzeSvg(
    svg(
      '<symbol id="s" viewBox="0 0 10 10" clip-path="url(#c2)"><rect width="10" height="10"/></symbol>' +
        '<clipPath id="c2"><rect width="10" height="10"/></clipPath>' +
        '<use href="#s" width="24" height="24"/>',
    ),
  );
  assert.deepEqual(symbol.unresolved, []);
});

test('a half-parsed path inside a viewport is reported, not dropped', () => {
  // `bboxOfShapes` returns null when a path only partly parsed, and both
  // viewport checks treat null as "nothing to measure" — the shape disappeared
  // and the remaining ink kept the report looking fine.
  const shape = analyzeSvg(
    svg(
      '<symbol id="s"><path d="M0 0 L"/><rect x="4" y="4" width="16" height="16"/></symbol>' +
        '<use href="#s" width="24" height="24"/>',
    ),
  );
  assert.match(shape.unresolved.join(), /unparsed-path/);
  assert.equal(checkShape(shape, { target: 'sym-path.svg' }).verdict, 'unknown');
});

test('empty moveto fragments are not duplicate outlines', () => {
  // `M4 4z` twice paints nothing twice. Both fragments share a degenerate box
  // and an area of zero, so the duplicate-outline test called them one region
  // drawn twice and threw away the icon's real ink with them.
  const shape = analyzeSvg(svg('<path d="M4 4zM4 4z"/><rect x="2" y="0" width="20" height="24"/>'));
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.area, 480, 1e-6);

  // The same test on two outlines that do paint is still a refusal: equal box
  // and equal area do not prove equal shape, so the answer stays `unknown`.
  const duplicate = analyzeSvg(
    svg('<path d="M0 0h10v10h-10z M0 0h10v10h-10z"/><rect x="14" y="0" width="10" height="24"/>'),
  );
  assert.match(duplicate.unresolved.join(), /overlapping-subpaths/);
});

test('a subpath whose area cancels to nothing is refused, never dropped', () => {
  // A figure-eight is two triangles joined at (12,12) with opposite windings:
  // the shoelace sum is exactly zero while both paint. Dropping it as "no area"
  // left the rest of the canvas reporting `ok` as if the glyph did not exist.
  const only = analyzeSvg(svg('<path d="M12 12 L4 2 L2 12 L12 12 L20 2 L22 12 Z"/>'));
  assert.match(only.unresolved.join(), /self-intersecting/);

  const beside = analyzeSvg(
    svg('<path d="M12 12 L4 2 L2 12 L12 12 L20 2 L22 12 Z"/><rect x="10" y="10" width="4" height="4"/>'),
  );
  assert.match(beside.unresolved.join(), /self-intersecting/);
  assert.equal(checkShape(beside, { target: 'fig8.svg' }).verdict, 'unknown');
});

test('an animation that reaches zero paint is caught in every spelling', () => {
  // `#00000000` and `rgba(0,0,0,0)` say "transparent" without the word, and `.0`
  // / `0%` are zero opacity just as much as `0`. A colour cycle is the control:
  // it repaints without moving anything, so it must stay measurable.
  const cases = [
    '<animate attributeName="fill" from="#000" to="#00000000" dur="1s"/>',
    '<animate attributeName="fill" from="#000" to="rgba(0,0,0,0)" dur="1s"/>',
    '<animate attributeName="opacity" from="1" to=".0" dur="1s"/>',
    '<animate attributeName="opacity" from="1" to="0%" dur="1s"/>',
  ];
  for (const animation of cases) {
    const shape = analyzeSvg(svg(`<rect width="24" height="24">${animation}</rect>`));
    assert.match(shape.unresolved.join(), /animated-ink/, animation);
  }
  const cycle = analyzeSvg(
    svg('<rect width="24" height="24"><animate attributeName="fill" from="#000" to="#f00" dur="1s"/></rect>'),
  );
  assert.deepEqual(cycle.unresolved, []);
});

test('a > inside an attribute value does not cut the tag', () => {
  // `data-name="a>b"` is legal XML. Scanning to the first `>` dropped every
  // attribute after it, so a path lost its `d` (a shape with no `d` is not ink)
  // and the file measured as if that glyph had never been drawn.
  const withGt = analyzeSvg(
    svg('<path data-name="a>b" d="M0 0H8V8H0Z"/><rect x="10" y="10" width="4" height="4"/>'),
  );
  const control = analyzeSvg(svg('<path d="M0 0H8V8H0Z"/><rect x="10" y="10" width="4" height="4"/>'));
  assert.deepEqual(withGt.unresolved, []);
  near(withGt.ink.area, control.ink.area, 1e-9);
  near(withGt.ink.area, 80, 1e-9);

  // Single quotes are attribute delimiters too.
  const single = analyzeSvg(
    svg("<path data-name='a>b' d='M0 0H8V8H0Z'/><rect x='10' y='10' width='4' height='4'/>"),
  );
  near(single.ink.area, 80, 1e-9);
});

// --- paint validity, not just "is it the string none" -----------------------

test('a paint value CSS cannot parse is dropped, not painted', () => {
  // An invalid declaration never reaches the element, so `stroke` keeps its
  // initial value (`none`) and the shape is empty. Reading the junk string as a
  // colour put a 128-unit band on a canvas the render leaves blank.
  for (const paint of ['notacolor', '3', '3px', '#12345', 'rgb(1,2', '']) {
    const shape = analyzeSvg(
      svg(`<rect x="4" y="4" width="16" height="16" fill="none" stroke="${paint}" stroke-width="2"/>`),
    );
    assert.equal(shape.noInk, true, `stroke="${paint}"`);
  }
  // `fill` falls back to its initial value, black — which still paints, so the
  // area is the rectangle either way. The point is that it is not *absent*.
  const filled = analyzeSvg(svg('<rect x="4" y="4" width="16" height="16" fill="notacolor"/>'));
  near(filled.ink.area, 256, 1e-9);
});

test('a colour function this pass does not model is refused, not guessed', () => {
  const shape = analyzeSvg(svg('<rect width="24" height="24" fill="futurecolor(1 2 3)"/>'));
  assert.ok(shape.unresolved.includes('unparsed-paint'), JSON.stringify(shape.unresolved));
});

test('a negative opacity paints nothing, because CSS clamps it to zero', () => {
  for (const body of [
    '<rect x="4" y="4" width="16" height="16" fill-opacity="-1"/>',
    '<g opacity="-1"><rect x="4" y="4" width="16" height="16"/></g>',
    '<rect x="4" y="4" width="16" height="16" fill="none" stroke="#000" stroke-width="2" stroke-opacity="-1"/>',
  ]) {
    const shape = analyzeSvg(svg(body));
    assert.equal(shape.noInk, true, body);
  }
  // Above 1 clamps to 1 and still paints.
  const opaque = analyzeSvg(svg('<rect x="4" y="4" width="16" height="16" opacity="4"/>'));
  near(opaque.ink.area, 256, 1e-9);
});

test('inherit takes the parent paint, which may be none', () => {
  const empty = analyzeSvg(svg('<g fill="none"><rect x="4" y="4" width="16" height="16" fill="inherit"/></g>'));
  assert.equal(empty.noInk, true);
  const solid = analyzeSvg(svg('<g fill="#000"><rect x="4" y="4" width="16" height="16" fill="inherit"/></g>'));
  near(solid.ink.area, 256, 1e-9);
  // `initial` restores black for fill and none for stroke.
  const initial = analyzeSvg(
    svg('<g fill="none"><rect x="4" y="4" width="16" height="16" fill="initial"/></g>'),
  );
  near(initial.ink.area, 256, 1e-9);
  const stroked = analyzeSvg(
    svg('<g stroke="#000"><rect x="4" y="4" width="16" height="16" fill="none" stroke="initial" stroke-width="2"/></g>'),
  );
  assert.equal(stroked.noInk, true);
});

test('a CSS comment inside a value is whitespace', () => {
  const shape = analyzeSvg(svg('<style>.a{fill:/* hidden */none}</style><rect class="a" x="4" y="4" width="16" height="16"/>'));
  assert.equal(shape.noInk, true);
  // The same in an inline style, which is CSS too.
  const inline = analyzeSvg(svg('<rect x="4" y="4" width="16" height="16" style="fill:/* x */none"/>'));
  assert.equal(inline.noInk, true);
});

test('a stylesheet for another medium does not paint', () => {
  const shape = analyzeSvg(
    svg('<style media="print">.a{fill:#000}</style><rect class="a" x="4" y="4" width="16" height="16" fill="none"/>'),
  );
  assert.equal(shape.noInk, true);
  assert.ok(shape.unresolved.includes('stylesheet-conditional'), JSON.stringify(shape.unresolved));
  // `media="screen"` applies.
  const screen = analyzeSvg(
    svg('<style media="screen">.a{fill:#000}</style><rect class="a" x="4" y="4" width="16" height="16" fill="none"/>'),
  );
  near(screen.ink.area, 256, 1e-9);
});

// --- the ink box is made of ink --------------------------------------------

test('a subpath that encloses nothing does not stretch the ink box', () => {
  // A stray `M0 0` or a bare line spans a box and paints nothing. It used to be
  // unioned into the ink box, which pulled a correct 4..20 square back to the
  // origin: `off` by 2px, with a `viewBox="-2 -2 24 24"` suggestion that would
  // have broken the icon.
  for (const extra of ['M0 0', 'M1 1 L2 1', 'M1 1 L2 2']) {
    const shape = analyzeSvg(svg(`<path d="M4 4 H20 V20 H4 Z ${extra}"/>`));
    assert.deepEqual(shape.unresolved, [], extra);
    near(shape.ink.area, 256, 1e-9);
    near(shape.ink.bbox.minX, 4, 1e-9);
    near(shape.ink.bbox.maxX, 20, 1e-9);
    const report = checkShape(shape, { mode: 'standalone', target: 'stray.svg' });
    assert.equal(report.verdict, 'ok', `${extra}: ${JSON.stringify(report.findings)}`);
  }
  // A stroked bare line *is* ink and still widens the box.
  const stroked = analyzeSvg(svg('<path d="M4 4 H20 V20 H4 Z M1 1 L2 2" fill="none" stroke="#000" stroke-width="2"/>'));
  near(stroked.ink.bbox.minX, 0, 1e-6);
});

test('a prefixed element is the element, not an invisible container', () => {
  // `xmlns:svg="…/svg"` makes `<svg:rect>` the same node as `<rect>`. Keeping the
  // prefix meant the shape test missed and the geometry vanished silently: 400
  // units² became 16.
  const prefixed = analyzeSvg(
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:svg="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
      + '<svg:rect x="2" y="2" width="20" height="20"/></svg>',
  );
  assert.deepEqual(prefixed.unresolved, []);
  near(prefixed.ink.area, 400, 1e-9);
  near(prefixed.ink.bbox.minX, 2, 1e-9);
});

// --- outlines that share a region are not additive -------------------------

test('sibling outlines that overlap are refused, in both windings', () => {
  // Two holes offset by 0.1: the overlap comes back to winding −1, so it is
  // painted and both holes were subtracted in full. 572 units² at (12.02, 12.02)
  // measured as 376 at (13.57, 13.57).
  const holes = analyzeSvg(svg('<path d="M0 0H24V24H0Z M4 4V14H14V4Z M4.1 4.1V14.1H14.1V4.1Z"/>'));
  assert.ok(holes.unresolved.includes('overlapping-subpaths'), JSON.stringify(holes.unresolved));
  // Two solids wound the same way paint their union once; the sum counts the
  // overlap twice (252 painted, 288 summed).
  const solids = analyzeSvg(svg('<path d="M2 2H14V14H2Z M8 8H20V20H8Z"/>'));
  assert.ok(solids.unresolved.includes('overlapping-subpaths'), JSON.stringify(solids.unresolved));
});

test('outlines that merely touch stay measurable', () => {
  // Butted rectangles share an edge and add up correctly; refusing them would
  // cost every icon drawn as two halves.
  const butted = analyzeSvg(svg('<path d="M2 2H12V22H2Z M12 2H22V22H12Z"/>'));
  assert.deepEqual(butted.unresolved, []);
  near(butted.ink.area, 400, 1e-9);
  // A hole touching its container at one corner subtracts (382, not 418).
  const corner = analyzeSvg(svg('<path d="M0 0 H20 V20 H0 Z M0 0 V6 L6 0 Z"/>'));
  assert.deepEqual(corner.unresolved, []);
  near(corner.ink.area, 382, 1e-9);
});

// --- transforms that promise more than they can deliver --------------------

test('a non-uniform scale scales the stroke band by the area factor', () => {
  // Band area is `perimeter × width`, and a linear map scales area by |det|. The
  // old code multiplied the already-stretched perimeter by the mean scale, which
  // counted the scale twice: 500 where 4 × (40 × 2) = 320.
  const shape = analyzeSvg(
    svg('<rect x="2" y="7" width="10" height="10" fill="none" stroke="#000" stroke-width="2" transform="scale(4,1)"/>'),
  );
  near(shape.ink.area, 320, 1e-6);
  // The band is 4× wider across x than across y, so the box pads per axis.
  near(shape.ink.bbox.minX, 4, 1e-6);
  near(shape.ink.bbox.maxX, 52, 1e-6);
  near(shape.ink.bbox.minY, 6, 1e-6);
  near(shape.ink.bbox.maxY, 18, 1e-6);
});

test('a clip in a rotated space is refused, not widened', () => {
  // The bounding box of a rotated rect is a *superset* of the clip, so "does the
  // ink fit" answers yes for ink the render cuts away.
  const shape = analyzeSvg(
    '<svg viewBox="0 0 10 10"><defs><clipPath id="c"><rect width="10" height="10"/></clipPath></defs>'
      + '<g transform="rotate(45 5 5)"><g clip-path="url(#c)"><rect x="-2" y="4" width="4" height="4"/></g></g></svg>',
  );
  assert.ok(shape.unresolved.includes('clip-path'), JSON.stringify(shape.unresolved));
  // An axis-aligned ancestor still resolves.
  const plain = analyzeSvg(
    '<svg viewBox="0 0 10 10"><defs><clipPath id="c"><rect width="10" height="10"/></clipPath></defs>'
      + '<g clip-path="url(#c)"><rect x="2" y="2" width="4" height="4"/></g></svg>',
  );
  assert.deepEqual(plain.unresolved, []);
  near(plain.ink.area, 16, 1e-9);
});

test('a shape whose area overflows is refused, not silently dropped', () => {
  // `scale(1e308)` makes the shoelace sum NaN, and NaN is not `> 0`, so the shape
  // disappeared without a reason while the rest of the file reported `ok`.
  const shape = analyzeSvg(
    svg('<g transform="scale(1e308)"><rect x="4" y="4" width="16" height="16"/></g>'
      + '<rect x="4" y="4" width="16" height="16"/>'),
  );
  assert.ok(shape.unresolved.includes('non-finite-ink'), JSON.stringify(shape.unresolved));
});

test('invisible text is not unmeasurable ink', () => {
  // `<text fill="none">` paints nothing, so refusing it made a file with one
  // invisible label unmeasurable.
  const shape = analyzeSvg(svg('<text x="2" y="20" fill="none">hi</text><rect x="4" y="4" width="16" height="16"/>'));
  assert.deepEqual(shape.unresolved, []);
  near(shape.ink.area, 256, 1e-9);
  // Visible text is still refused: it is ink this pass cannot measure.
  const visible = analyzeSvg(svg('<text x="2" y="20">hi</text><rect x="4" y="4" width="16" height="16"/>'));
  assert.ok(visible.unresolved.includes('unsupported-ink:text'), JSON.stringify(visible.unresolved));
  const hidden = analyzeSvg(
    svg('<text x="2" y="20" visibility="hidden">hi</text><rect x="4" y="4" width="16" height="16"/>'),
  );
  assert.deepEqual(hidden.unresolved, []);
});
