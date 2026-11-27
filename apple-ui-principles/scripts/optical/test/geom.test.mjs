import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  flattenPath,
  subpathSignedArea,
  subpathCentroid,
  netShape,
  bboxOfPoints,
  parseTransform,
  applyMatrix,
  multiplyMatrix,
} from '../geom.mjs';

const near = (actual, expected, eps = 1e-6) =>
  assert.ok(Math.abs(actual - expected) < eps, `${actual} != ${expected} (±${eps})`);

test('square: area 256, centroid at centre', () => {
  const subs = flattenPath('M4 4 H20 V20 H4 Z');
  assert.equal(subs.length, 1);
  const shape = netShape(subs);
  near(shape.area, 256, 1e-6);
  near(shape.cx, 12);
  near(shape.cy, 12);
});

test('play triangle: area 77, centroid x = 11.6667', () => {
  const subs = flattenPath('M8 5 L8 19 L19 12 Z');
  const shape = netShape(subs);
  near(shape.area, 77, 1e-6);
  near(shape.cx, 35 / 3);
  near(shape.cy, 12);
});

test('signed area is negative for counter-clockwise subpath', () => {
  const cw = flattenPath('M0 0 H10 V10 H0 Z')[0];
  const ccw = flattenPath('M0 0 V10 H10 V0 Z')[0];
  assert.ok(subpathSignedArea(cw) > 0);
  assert.ok(subpathSignedArea(ccw) < 0);
  assert.equal(subpathCentroid(cw).signedArea, 10 * 10);
});

test('holes subtract from net area but keep centroid', () => {
  const subs = flattenPath('M0 0 H20 V20 H0 Z M8 8 H12 V12 H8 Z');
  const shape = netShape(subs);
  // Same winding -> both positive -> subtraction requires opposite winding.
  // Instead assert the helper reports the summed signed area faithfully.
  near(shape.area, 400 + 16, 1e-6);

  const holed = flattenPath('M0 0 H20 V20 H0 Z M8 8 V12 H12 V8 Z');
  const netted = netShape(holed);
  near(netted.area, 400 - 16, 1e-6);
  near(netted.cx, 10);
  near(netted.cy, 10);
});

test('circle approximated by arcs: area within 0.6 of PI r^2', () => {
  const subs = flattenPath('M4 12 A8 8 0 1 0 20 12 A8 8 0 1 0 4 12 Z');
  const shape = netShape(subs);
  assert.ok(Math.abs(shape.area - Math.PI * 64) < 0.6, `area=${shape.area}`);
  near(shape.cx, 12, 1e-3);
  near(shape.cy, 12, 1e-3);
});

test('bbox of points', () => {
  const box = bboxOfPoints([
    [1, 2],
    [3, 0],
    [-1, 5],
  ]);
  assert.deepEqual(box, { minX: -1, minY: 0, maxX: 3, maxY: 5 });
});

test('transform: translate(2,3) scale(2) applies scale first', () => {
  const m = parseTransform('translate(2,3) scale(2)');
  const [x, y] = applyMatrix(m, 1, 1);
  near(x, 4);
  near(y, 5);
});

test('transform: rotate(90) about origin maps (1,0) to (0,1)', () => {
  const m = parseTransform('rotate(90)');
  const [x, y] = applyMatrix(m, 1, 0);
  near(x, 0, 1e-9);
  near(y, 1, 1e-9);
});

test('matrix multiplication order matches SVG nesting', () => {
  const outer = parseTransform('translate(10,0)');
  const inner = parseTransform('scale(2)');
  const combined = multiplyMatrix(outer, inner);
  const [x] = applyMatrix(combined, 1, 0);
  near(x, 12);
});

test('zero-length and empty paths do not throw', () => {
  assert.deepEqual(flattenPath(''), []);
  const subs = flattenPath('M4 4');
  const shape = netShape(subs);
  // A lone moveto contributes no area and should not yield NaN.
  assert.ok(Number.isFinite(shape.area));
});
