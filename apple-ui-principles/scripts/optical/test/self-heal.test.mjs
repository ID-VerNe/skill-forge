import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';

const cli = fileURLToPath(new URL('../cli.mjs', import.meta.url));
const fixture = (name) => fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url));
const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
const heal = (...args) => run('check', '--self-heal', ...args);

/** Case-insensitive: Windows hands back the on-disk spelling of a real path. */
const samePath = (a, b) =>
  fs.realpathSync.native(a).toLowerCase() === fs.realpathSync.native(b).toLowerCase();

function write(file, text) {
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, text);
}

/** A fake repo, a fake home, and no installs yet. */
function sandbox() {
  const root = mkdtempSync(join(tmpdir(), 'optical-heal-'));
  // The basename matters: installs are looked up as <home>/<agent>/apple-ui-principles.
  const skill = join(root, 'repo', 'apple-ui-principles');
  write(join(skill, 'SKILL.md'), '---\nname: apple-ui-principles\n---\n\nRunning the optical checker\n');
  write(join(skill, 'scripts', 'optical', 'rule.mjs'), 'export const x = 1;\n');
  write(join(skill, 'references', 'model.md'), '# model\n');
  const home = join(root, 'home');
  mkdirSync(home, { recursive: true });
  return { root, skill, home };
}

/** The September problem: a real directory holding an old copy of the skill. */
function staleJunction(home, agentDir = '.claude/skills') {
  const path = join(home, agentDir, 'apple-ui-principles');
  write(join(path, 'SKILL.md'), 'september copy\n');
  return path;
}

/** A healthy hardlink mirror, which git then breaks by replacing a file. */
function mirror(home, skill) {
  const base = join(home, '.gemini', 'config', 'skills', 'apple-ui-principles');
  for (const rel of ['SKILL.md', 'scripts/optical/rule.mjs', 'references/model.md']) {
    mkdirSync(dirname(join(base, rel)), { recursive: true });
    fs.linkSync(join(skill, rel), join(base, rel));
  }
  return base;
}

test('a stale install is relinked and an absent agent is left alone', () => {
  const { skill, home } = sandbox();
  const stale = staleJunction(home);

  const result = heal('--home', home, '--skill-dir', skill);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.lstatSync(stale).isSymbolicLink(), true);
  assert.equal(samePath(stale, skill), true);
  assert.equal(readFileSync(join(stale, 'SKILL.md'), 'utf8'), readFileSync(join(skill, 'SKILL.md'), 'utf8'));
  // Repairing must never look like installing: no Trae CN was there to repair.
  assert.equal(fs.existsSync(join(home, '.trae-cn')), false);
  assert.match(result.stderr, /not installed/);
  // Healing with no paths is a complete invocation, not a usage error.
  assert.equal(result.stdout, '');
});

test('a mirror whose hardlinks git broke is relinked, and leftovers are pruned', () => {
  const { skill, home } = sandbox();
  const base = mirror(home, skill);

  // What `git checkout` does to a hardlink: a new inode, stale content, no error.
  fs.unlinkSync(join(base, 'SKILL.md'));
  writeFileSync(join(base, 'SKILL.md'), 'stale\n');
  // What a previous release left behind.
  writeFileSync(join(base, 'removed-in-2.0.md'), 'gone\n');

  const result = heal('--home', home, '--skill-dir', skill);

  assert.equal(result.status, 0, result.stderr);
  const mirrored = join(base, 'SKILL.md');
  assert.equal(readFileSync(mirrored, 'utf8'), readFileSync(join(skill, 'SKILL.md'), 'utf8'));
  assert.equal(fs.statSync(mirrored).ino, fs.statSync(join(skill, 'SKILL.md')).ino);
  assert.equal(fs.existsSync(join(base, 'removed-in-2.0.md')), false);
  assert.match(result.stderr, /repaired .*relinked 1, pruned 1/);
});

test('a correct install is not touched at all', () => {
  const { skill, home } = sandbox();
  const junction = staleJunction(home);
  heal('--home', home, '--skill-dir', skill); // first pass: relinks it
  const before = fs.lstatSync(junction).ino;

  const second = heal('--home', home, '--skill-dir', skill);

  assert.equal(second.status, 0, second.stderr);
  assert.equal(fs.lstatSync(junction).ino, before, 'a good junction was rebuilt');
  assert.match(second.stderr, /^self-heal: 0 changed/m);
});

test('a junction pointing at the old repo location is repointed', () => {
  const { root, skill, home } = sandbox();
  const elsewhere = join(root, 'old-clone', 'apple-ui-principles');
  write(join(elsewhere, 'SKILL.md'), 'old clone\n');
  const install = join(home, '.qoder', 'skills', 'apple-ui-principles');
  mkdirSync(dirname(install), { recursive: true });
  fs.symlinkSync(elsewhere, install, process.platform === 'win32' ? 'junction' : 'dir');

  const result = heal('--home', home, '--skill-dir', skill);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(samePath(install, skill), true);
  assert.match(result.stderr, /relinked .*was unlinked-link/);
});

test('heal output goes to stderr so --json stays parseable', () => {
  const { skill, home } = sandbox();
  staleJunction(home);

  const result = run(
    'check', fixture('icons/square.svg'), '--json', '--self-heal',
    '--home', home, '--skill-dir', skill,
  );

  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(result.stdout); // throws if a heal line leaked
  assert.equal(report.verdict, 'ok');
  assert.match(result.stderr, /self-heal/);
});

test('--home without --self-heal is refused instead of ignored', () => {
  const result = run('check', fixture('icons/square.svg'), '--home', '/tmp');
  assert.equal(result.status, 64);
  assert.match(result.stderr, /only apply to --self-heal/);
});

test('--self-heal is refused on the font subcommand', () => {
  const result = run('font', fixture('icons/square.svg'), '--size', '16', '--self-heal');
  assert.equal(result.status, 64);
  assert.match(result.stderr, /nothing to do with/);
});

test('running from an installed copy is refused instead of becoming the source', () => {
  const { skill, home } = sandbox();
  const install = staleJunction(home);

  // Passing the install itself as --skill-dir is what a run from that copy does.
  const result = heal('--home', home, '--skill-dir', install);

  assert.equal(result.status, 64);
  assert.match(result.stderr, /installed copy/);
  // Nothing may be repointed at a copy: that builds a chain git can break.
  assert.equal(fs.lstatSync(install).isSymbolicLink(), false);
  assert.equal(readFileSync(join(install, 'SKILL.md'), 'utf8'), 'september copy\n');
  assert.equal(fs.existsSync(join(home, '.qoder')), false);
});

test('a checkout that sits at an install position is left in place', () => {
  const { home } = sandbox();
  // Someone cloned the repo straight into the install position.
  const install = join(home, '.claude', 'skills', 'apple-ui-principles');
  write(join(install, 'SKILL.md'), 'source\n');
  write(join(home, '.git'), 'gitdir: nowhere\n'); // makes it a checkout, not a copy

  const result = heal('--home', home, '--skill-dir', install);

  assert.equal(result.status, 0, result.stderr);
  // Replacing it with a junction to itself would have deleted the checkout.
  assert.equal(fs.lstatSync(install).isSymbolicLink(), false);
  assert.equal(readFileSync(join(install, 'SKILL.md'), 'utf8'), 'source\n');
  assert.match(result.stderr, /already correct/);
});

test('a heal that cannot finish exits 2, not 0', () => {
  const { home } = sandbox();
  const result = heal('--home', home, '--skill-dir', join(home, 'no-such-skill'));

  // 2 means "unknown". Reporting 0 here would claim the installs are fine.
  assert.equal(result.status, 2);
  assert.match(result.stderr, /self-heal failed/);
});
