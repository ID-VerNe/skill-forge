import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const cli = fileURLToPath(new URL('../cli.mjs', import.meta.url));
const fixture = (name) => fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url));
const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });

test('a certain defect exits 1', () => {
  const result = run('check', fixture('icons/play.svg'));
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stdout, /OFF/);
});

test('a clean icon exits 0', () => {
  const result = run('check', fixture('icons/square.svg'));
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /OK/);
});

test('unparseable input exits 2, not 1', () => {
  const result = run('check', fixture('css/broken.css'));
  assert.equal(result.status, 2, `${result.stdout}\n${result.stderr}`);
});

test('--json emits a single report object for one target', () => {
  const result = run('check', fixture('icons/play.svg'), '--json');
  const report = JSON.parse(result.stdout);
  assert.equal(report.version, 1);
  assert.equal(report.verdict, 'off');
  assert.equal(report.policy_source, 'builtin');
  assert.ok(Array.isArray(report.findings));
});

test('multiple targets return an array and the worst exit code', () => {
  const result = run('check', fixture('icons/square.svg'), fixture('icons/play.svg'), '--json');
  const reports = JSON.parse(result.stdout);
  assert.equal(reports.length, 2);
  assert.equal(result.status, 1);
});

test('--tolerance is refused so thresholds cannot be gamed', () => {
  const result = run('check', fixture('icons/play.svg'), '--tolerance', '99');
  assert.equal(result.status, 64);
  assert.match(result.stderr, /--policy/);
});

test('--policy is echoed back in the report', () => {
  const dir = mkdtempSync(join(tmpdir(), 'optical-policy-'));
  const policyPath = join(dir, 'loose.json');
  writeFileSync(policyPath, JSON.stringify({ toleranceScale: 4 }));
  const result = run('check', fixture('icons/play.svg'), '--policy', policyPath, '--json');
  const report = JSON.parse(result.stdout);
  assert.equal(report.policy_source, 'custom');
  assert.equal(report.policy_path, 'loose.json');
  // 1.83px against tol 0.5 * 4 = 2.0 -> no longer a defect
  assert.notEqual(report.verdict, 'off');
});

test('--explain prints the evidence trail', () => {
  const result = run('check', fixture('icons/play.svg'), '--explain');
  assert.match(result.stdout, /centroid=/);
  assert.match(result.stdout, /area=77/);
});

test('directories are checked as an icon set', () => {
  const result = run('check', fixture('icons/set'), '--json');
  const report = JSON.parse(result.stdout);
  assert.equal(report.mode, 'keyline');
  assert.ok(report.findings.some((f) => f.id === 'geometry/keyline-overshoot'));
});
