import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
import { parseCss, checkCss, checkTsx } from '../rule.mjs';

const fixture = (name) => fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url));
const load = (name) => readFile(fixture(name), 'utf8');
const ids = (report) => report.findings.map((f) => f.id);
const pick = (report, id) => report.findings.find((f) => f.id === id);

test('text-box on a flex container is reported as a no-op', async () => {
  const report = checkCss(await load('css/flex-textbox.css'), { target: 'flex-textbox.css' });
  const f = pick(report, 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(ids(report)));
  assert.equal(f.verdict, 'off');
  assert.equal(f.layer, 'exact');
  assert.match(f.evidence, /\.btn/);
});

test('text-box on a flex child must not be reported as a false positive', async () => {
  const report = checkCss(await load('css/textbox-child.css'), { target: 'textbox-child.css' });
  assert.ok(
    !report.findings.some((f) => f.id === 'rule/text-box-in-flex' && f.verdict === 'off'),
    JSON.stringify(report.findings, null, 2),
  );
  assert.equal(report.verdict, 'ok');
});

test('nested @layer blocks are tokenised, not mis-split', async () => {
  const { blocks, unresolved } = parseCss(await load('css/nested-layer.css'));
  assert.equal(unresolved, null);
  assert.ok(blocks.some((b) => b.selector.includes('.card')));
  const report = checkCss(await load('css/nested-layer.css'), { target: 'nested-layer.css' });
  assert.equal(pick(report, 'rule/text-box-in-flex').verdict, 'off');
});

test('a closing brace inside a string does not corrupt the block map', async () => {
  const css = await load('css/brace-in-string.css');
  const { blocks, unresolved } = parseCss(css);
  assert.equal(unresolved, null);
  assert.equal(blocks.length, 2);
  assert.deepEqual(
    blocks.map((b) => b.selector).sort(),
    ['.btn', '.foo::after'],
  );
  const report = checkCss(css, { target: 'brace-in-string.css' });
  assert.equal(pick(report, 'rule/text-box-in-flex').verdict, 'off');
});

test('hard-coded vertical nudges on text are surfaced as heuristic', async () => {
  const report = checkCss(await load('css/nudge.css'), { target: 'nudge.css' });
  const f = pick(report, 'rule/hardcoded-vertical-nudge');
  assert.ok(f, JSON.stringify(ids(report)));
  assert.equal(f.layer, 'heuristic');
  assert.equal(f.verdict, 'nudge');
  assert.match(f.suggested.value, /text-box/);
});

test('unbalanced braces degrade to unknown instead of guessing', () => {
  const broken = '.a { display: flex; text-box: trim-both;';
  const { unresolved } = parseCss(broken);
  assert.ok(unresolved, 'expected an unresolved marker');
  const report = checkCss(broken, { target: 'broken.css' });
  assert.equal(report.verdict, 'unknown');
});

test('tsx: flex + text-box-trim on the same element is off', async () => {
  const report = checkTsx(await load('tsx/button.tsx'), { target: 'button.tsx' });
  const f = pick(report, 'rule/text-box-in-flex');
  assert.ok(f, JSON.stringify(ids(report)));
  assert.equal(f.verdict, 'off');
});

test('tsx: nested radii produce the expected calc() expression', async () => {
  const report = checkTsx(await load('tsx/concentric.tsx'), { target: 'concentric.tsx' });
  const f = pick(report, 'rule/non-concentric-radius');
  assert.ok(f, JSON.stringify(ids(report)));
  assert.equal(f.suggested.value, 'calc(16px - 8px)');
});

test('css-only input cannot verify nesting and says so', async () => {
  const report = checkCss('.a { border-radius: 16px; padding: 8px; } .b { border-radius: 6px; }', {
    target: 'nesting.css',
  });
  assert.equal(
    report.findings.filter((f) => f.id === 'rule/non-concentric-radius').length,
    0,
    'css alone gives no parent-child relation; do not invent one',
  );
});
