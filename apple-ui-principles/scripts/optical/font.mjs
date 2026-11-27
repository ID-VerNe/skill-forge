// Font metrics for the cap-midpoint check (#7).
//
// Only sfnt containers (.ttf / .otf) are supported. WOFF2 needs table
// reconstruction and is refused on purpose: a wrong capHeight produces a
// confidently wrong offset, which is exactly the failure mode this toolkit
// exists to prevent.

const SFNT_VERSIONS = new Set([0x00010000, 0x4f54544f, 0x74727565]); // 1.0, OTTO, true

function fail(code, message) {
  const err = new Error(message);
  err.code = code;
  return err;
}

/**
 * Offset of the visual centre of capital letters relative to the centre of the
 * line box, in CSS px. Negative means the glyphs look higher than the box.
 *
 * Half-leading shifts the cap top and the box centre by the same amount, so
 * line-height cancels out entirely:
 *   delta = fontSize * (ascender + descender - capHeight) / (2 * upem)
 */
export function capMidpointDelta(metrics, { fontSize, lineHeight } = {}) {
  if (!metrics || !(metrics.upem > 0)) {
    throw fail('ERR_FONT_METRICS', 'font metrics need a positive unitsPerEm');
  }
  const { ascender, descender, capHeight } = metrics;
  for (const [name, value] of Object.entries({ ascender, descender, capHeight })) {
    if (!Number.isFinite(value)) {
      throw fail('ERR_FONT_METRICS', `font metrics missing ${name}`);
    }
  }
  if (!(fontSize > 0)) {
    throw fail('ERR_FONT_METRICS', 'fontSize must be positive');
  }
  void lineHeight; // accepted for API symmetry; it cancels out (see above)
  return (fontSize * (ascender + descender - capHeight)) / (2 * metrics.upem);
}

/**
 * Read the four metrics the check needs out of an sfnt buffer.
 * @param {Buffer|Uint8Array} buffer
 */
export function readFontMetrics(buffer) {
  const buf = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer);
  if (buf.length < 12) throw fail('ERR_FONT_FORMAT', 'file is too small to be a font');

  const magic = buf.readUInt32BE(0);
  if (buf.toString('latin1', 0, 4) === 'wOF2') {
    throw fail('ERR_FONT_FORMAT', 'WOFF2 is not supported; point the check at the .ttf/.otf source');
  }
  if (!SFNT_VERSIONS.has(magic)) {
    throw fail('ERR_FONT_FORMAT', 'not an sfnt font (expected .ttf or .otf)');
  }

  const numTables = buf.readUInt16BE(4);
  if (numTables === 0 || 12 + numTables * 16 > buf.length) {
    throw fail('ERR_FONT_FORMAT', 'truncated table directory');
  }

  const tables = new Map();
  for (let i = 0; i < numTables; i += 1) {
    const base = 12 + i * 16;
    const tag = buf.toString('latin1', base, base + 4);
    const offset = buf.readUInt32BE(base + 8);
    const length = buf.readUInt32BE(base + 12);
    if (offset + length <= buf.length) tables.set(tag, { offset, length });
  }

  const head = tables.get('head');
  const hhea = tables.get('hhea');
  const os2 = tables.get('OS/2');
  if (!head || !hhea) throw fail('ERR_FONT_FORMAT', 'missing head or hhea table');

  const upem = head.offset + 18 + 2 <= buf.length ? buf.readUInt16BE(head.offset + 18) : 0;
  if (!upem) throw fail('ERR_FONT_METRICS', 'unitsPerEm is zero');

  const ascender = buf.readInt16BE(hhea.offset + 4);
  const descender = buf.readInt16BE(hhea.offset + 6);

  let capHeight;
  if (os2 && os2.offset + 2 <= buf.length) {
    const version = buf.readUInt16BE(os2.offset);
    if (version >= 2 && os2.offset + 90 <= buf.length) {
      capHeight = buf.readInt16BE(os2.offset + 88);
    }
  }
  if (!capHeight) {
    throw fail('ERR_FONT_METRICS', 'OS/2 table has no sCapHeight (version < 2)');
  }

  return { upem, ascender, descender, capHeight };
}
