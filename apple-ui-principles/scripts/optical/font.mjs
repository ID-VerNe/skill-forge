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
 *
 * The ascender/descender pair is the one the text engine actually uses for the
 * line box, **not** necessarily `hhea`. Chrome on Windows uses OS/2 `sTypo*`
 * when `fsSelection` bit 7 (`USE_TYPO_METRICS`) is set and `usWinAscent` /
 * `usWinDescent` otherwise. Calibri is the failure this distinction fixes:
 * hhea gives 1536/-512 (−2.109px at 32px) while win gives 1950/550 (+0.828px);
 * Chrome renders +0.844px. The sign was reversed. `metricSource` records which
 * pair was chosen so the number is auditable.
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

  const hheaAscender = buf.readInt16BE(hhea.offset + 4);
  const hheaDescender = buf.readInt16BE(hhea.offset + 6);

  let capHeight;
  let os2Version = 0;
  let selection = 0;
  let typoAscender = 0;
  let typoDescender = 0;
  let winAscender = 0;
  let winDescender = 0;
  if (os2 && os2.offset + 78 <= buf.length) {
    os2Version = buf.readUInt16BE(os2.offset);
    if (os2Version >= 1) {
      selection = buf.readUInt16BE(os2.offset + 62);
      typoAscender = buf.readInt16BE(os2.offset + 68);
      typoDescender = buf.readInt16BE(os2.offset + 70);
      winAscender = buf.readUInt16BE(os2.offset + 74);
      winDescender = buf.readUInt16BE(os2.offset + 76);
    }
    if (os2Version >= 2 && os2.offset + 90 <= buf.length) {
      capHeight = buf.readInt16BE(os2.offset + 88);
    }
  }
  if (!capHeight) {
    throw fail('ERR_FONT_METRICS', 'OS/2 table has no sCapHeight (version < 2)');
  }

  // Bit 7 says the typo pair is authoritative. A zero pair (common in generated
  // test fonts) is not authoritative — it would put the baseline off the canvas.
  let ascender;
  let descender;
  let metricSource;
  if ((selection & 0x80) && typoAscender > 0 && typoDescender < 0) {
    ascender = typoAscender;
    descender = typoDescender;
    metricSource = 'os2-typo';
  } else if (winAscender > 0 && winDescender > 0) {
    ascender = winAscender;
    descender = -winDescender;
    metricSource = 'os2-win';
  } else {
    ascender = hheaAscender;
    descender = hheaDescender;
    metricSource = 'hhea';
  }

  return { upem, ascender, descender, capHeight, metricSource, os2Version };
}
