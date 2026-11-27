import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { checkIconFile, checkIconSet, analyzeSvg } from '../icon.mjs';

const fixture = (name) => fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url));
const near = (actual, expected, eps = 1e-3) =>
  assert.ok(Math.abs(actual - expected) < eps, `${actual} != ${expected} (±${eps})`);
const find = (report, id) => report.findings.find((f) => f.id === id);

test('symmetric icons report exactly zero offset', async () => {
  for (const name of ['icons/square.svg', 'icons/circle.svg', 'icons/cross.svg']) {
    const report = await checkIconFile(fixture(name));
    const ink = find(report, 'geometry/ink-bbox');
    const centroid = find(report, 'geometry/centroid');
    near(ink.measured.dx, 0, 1e-6);
    near(ink.measured.dy, 0, 1e-6);
    near(centroid.measured.dx, 0, 1e-3);
    near(centroid.measured.dy, 0, 1e-3);
    assert.equal(report.verdict, 'ok', `${name} should be ok, got ${report.verdict}`);
  }
});

test('play triangle: centroid is 1.8333px left of the ink box centre', async () => {
  const report = await checkIconFile(fixture('icons/play.svg'));
  const centroid = find(report, 'geometry/centroid');
  near(centroid.measured.dx, -11 / 6);
  near(centroid.measured.dy, 0);
  assert.equal(centroid.layer, 'exact');
  assert.equal(centroid.verdict, 'off');
  assert.match(centroid.evidence, /area=77/);
});

test('off-centre ink is reported against the viewBox, not the ink box', async () => {
  const report = await checkIconFile(fixture('icons/ink-offset.svg'));
  const ink = find(report, 'geometry/ink-bbox');
  near(ink.measured.dx, -1);
  near(ink.measured.dy, 0);
  assert.equal(ink.verdict, 'nudge');
  // The ink itself is symmetric, so its centroid sits on its own bbox centre.
  assert.equal(find(report, 'geometry/centroid').verdict, 'ok');
});

test('stroke-only icons use the band model and include half the stroke width', async () => {
  const report = await checkIconFile(fixture('icons/stroke-arrow.svg'));
  assert.equal(report.strokeOnly, true);
  const { bbox } = report.ink;
  near(bbox.minX, 3);
  near(bbox.maxX, 19);
  near(bbox.minY, 6);
  near(bbox.maxY, 18);
});

test('viewBox origin is honoured', () => {
  const svg = '<svg viewBox="10 10 24 24"><rect x="12" y="12" width="20" height="20"/></svg>';
  const shape = analyzeSvg(svg);
  near(shape.ink.bbox.minX, 12, 1e-6);
  near(shape.ink.bbox.maxX, 32, 1e-6);
  near(shape.ink.centroid.cx, 22, 1e-6);
});

test('group transform is inherited by children', () => {
  const svg =
    '<svg viewBox="0 0 24 24"><g transform="translate(2,2)"><rect x="4" y="4" width="16" height="16"/></g></svg>';
  const shape = analyzeSvg(svg);
  near(shape.ink.bbox.minX, 6, 1e-6);
  near(shape.ink.bbox.maxX, 22, 1e-6);
  near(shape.ink.centroid.cx, 14, 1e-6);
});

test('keyline: only the under-filled icon leaves the set', async () => {
  const report = await checkIconSet(fixture('icons/set'));
  const flagged = report.findings.filter((f) => f.verdict !== 'ok');
  assert.equal(flagged.length, 1, JSON.stringify(report.findings, null, 2));
  assert.match(flagged[0].evidence, /c-small/);
  assert.equal(flagged[0].layer, 'heuristic');
  // Heuristic findings never escalate past nudge.
  assert.equal(flagged[0].verdict, 'nudge');
});

test('mode inference refuses when context is ambiguous', async () => {
  const report = await checkIconFile(fixture('icons/play.svg'), { mode: 'auto' });
  assert.equal(report.mode, 'standalone');
  const forced = await checkIconFile(fixture('icons/play.svg'), { mode: 'inline' });
  assert.equal(forced.mode, 'inline');
  assert.ok(
    forced.findings.some((f) => f.verdict === 'unknown'),
    'inline mode without text must not invent a verdict',
  );
});

test('keyline refuses a set that mixes stroke-only and filled icons', async () => {
  const report = await checkIconSet(fixture('icons/set-mixed'));
  assert.equal(report.verdict, 'unknown');
  const f = report.findings.find((x) => x.id === 'geometry/keyline-mixed-set');
  assert.ok(f, JSON.stringify(report.findings, null, 2));
  assert.match(f.evidence, /2\/3 icons are stroke-only/);
});

test('keyline refuses a set too small to establish a norm', async () => {
  const report = await checkIconSet(fixture('icons/set-small'));
  assert.equal(report.verdict, 'unknown');
  assert.match(report.findings[0].evidence, /need at least 3/);
});
