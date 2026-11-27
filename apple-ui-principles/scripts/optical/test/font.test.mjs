import { test } from 'node:test';
import assert from 'node:assert/strict';
import { capMidpointDelta, readFontMetrics } from '../font.mjs';

const near = (actual, expected, eps = 1e-6) =>
  assert.ok(Math.abs(actual - expected) < eps, `${actual} != ${expected} (±${eps})`);

const metrics = { upem: 1000, ascender: 800, descender: -200, capHeight: 700 };

test('cap midpoint sits above the line box centre', () => {
  // delta = fontSize * (ascender + descender - capHeight) / (2 * upem)
  //       = 16 * (800 - 200 - 700) / 2000 = -0.8
  near(capMidpointDelta(metrics, { fontSize: 16, lineHeight: 1.5 }), -0.8);
});

test('line-height cancels out of the cap-midpoint offset', () => {
  // half-leading shifts the cap top and the box centre by the same amount,
  // so the offset is line-height independent. Changing it must not move the result.
  near(capMidpointDelta(metrics, { fontSize: 16, lineHeight: 1 }), -0.8);
  near(capMidpointDelta(metrics, { fontSize: 16, lineHeight: 2.4 }), -0.8);
});

test('a font with cap height equal to the ascent has its visual centre higher still', () => {
  const tall = { upem: 1000, ascender: 1000, descender: -250, capHeight: 1000 };
  const delta = capMidpointDelta(tall, { fontSize: 10, lineHeight: 1.5 });
  // content = 12.5, box = 15, half-leading = 1.25, baseline = 11.25, cap top = 1.25
  // cap mid = 6.25, centre = 7.5 -> -1.25
  near(delta, -1.25);
});

test('missing cap height is not silently treated as zero', () => {
  assert.throws(() => capMidpointDelta({ upem: 1000, ascender: 800, descender: -200 }, {}), {
    code: 'ERR_FONT_METRICS',
  });
});

test('woff2 and other containers are refused with an actionable code', () => {
  const woff2 = Buffer.from('wOF2' + '\0'.repeat(60), 'binary');
  assert.throws(() => readFontMetrics(woff2), { code: 'ERR_FONT_FORMAT' });
});

test('garbage input throws rather than returning NaN metrics', () => {
  assert.throws(() => readFontMetrics(Buffer.from('not a font at all')), {
    code: 'ERR_FONT_FORMAT',
  });
});
