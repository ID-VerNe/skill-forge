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

// --- the line-box metrics come from OS/2, not hhea --------------------------
//
// Chrome on Windows uses sTypo* when fsSelection bit 7 is set and usWinAscent /
// usWinDescent otherwise. Calibri's hhea pair (1536/-512) predicts -2.109px at
// 32px where the win pair (1950/550) predicts +0.828px; Chrome renders +0.844px.
// Reading hhea reversed the sign of the compensation.

function makeFont({ version = 3, selection = 0x40, typo = [0, 0], win = [0, 0] } = {}) {
  const head = Buffer.alloc(54);
  head.writeUInt32BE(0x00010000, 0);
  head.writeUInt16BE(2048, 18);
  const hhea = Buffer.alloc(36);
  hhea.writeInt16BE(1536, 4);
  hhea.writeInt16BE(-512, 6);
  const os2 = Buffer.alloc(96);
  os2.writeUInt16BE(version, 0);
  os2.writeUInt16BE(selection, 62);
  os2.writeInt16BE(typo[0], 68);
  os2.writeInt16BE(typo[1], 70);
  os2.writeUInt16BE(win[0], 74);
  os2.writeUInt16BE(win[1], 76);
  os2.writeInt16BE(1294, 88);
  const tables = [['head', head], ['hhea', hhea], ['OS/2', os2]];
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

test('the win metrics replace hhea when USE_TYPO_METRICS is not set', () => {
  const m = readFontMetrics(makeFont({ win: [1950, 550] }));
  assert.equal(m.metricSource, 'os2-win');
  assert.equal(m.ascender, 1950);
  assert.equal(m.descender, -550);
  near(capMidpointDelta(m, { fontSize: 32 }), 0.828125);
});

test('USE_TYPO_METRICS selects the typo pair', () => {
  const m = readFontMetrics(makeFont({ selection: 0xc0, typo: [1000, -300], win: [1950, 550] }));
  assert.equal(m.metricSource, 'os2-typo');
  near(capMidpointDelta(m, { fontSize: 32 }), 32 * (700 - 1294) / 4096);
});

test('an unset OS/2 pair falls back to hhea rather than putting the baseline at zero', () => {
  const m = readFontMetrics(makeFont());
  assert.equal(m.metricSource, 'hhea');
  near(capMidpointDelta(m, { fontSize: 32 }), -2.109375);
});
