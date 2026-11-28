#!/usr/bin/env node
// Keep every agent's installed copy of this skill pointing at the repository.
//
// Two link strategies, because the agents differ:
//
//   junction  WorkBuddy / Claude Code / Trae CN / Qoder. A directory junction is
//             resolved by path on every access, so it never goes stale: a
//             `git pull` in the repo is live immediately, with no sync step.
//
//   mirror    Gemini CLI. Hardlinks work on files, never on directories, so the
//             install is a real tree whose files share inodes with the repo.
//             The catch is that git does not know about inodes: when it replaces
//             a file (`checkout`, `merge`, `stash pop`) it writes a new one, and
//             the mirror silently reverts to a stale independent copy. Nothing
//             errors. That is the failure `--self-heal` exists to repair.
//
// The repair only touches install positions that already exist. It never
// creates one: a machine without Trae CN should not grow a `~/.trae-cn` just
// because someone ran a checker.
//
// Run directly to sync without the CLI:
//   node scripts/sync-installs.mjs [--home <dir>] [--skill-dir <dir>]

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** Where each agent looks for a skill, relative to the home directory. */
export const AGENTS = [
  { id: 'workbuddy', dir: '.workbuddy/skills', mode: 'junction' },
  { id: 'claude-code', dir: '.claude/skills', mode: 'junction' },
  { id: 'trae-cn', dir: '.trae-cn/skills', mode: 'junction' },
  { id: 'qoder', dir: '.qoder/skills', mode: 'junction' },
  { id: 'gemini-cli', dir: '.gemini/config/skills', mode: 'mirror' },
];

/** Windows paths are case-insensitive; comparing them as strings is not. */
function samePath(a, b) {
  const fold = (p) => (process.platform === 'win32' ? p.toLowerCase() : p);
  return fold(path.resolve(a)) === fold(path.resolve(b));
}

/** True when `child` is `parent` or lives underneath it. */
function contains(parent, child) {
  const rel = path.relative(path.resolve(parent), path.resolve(child));
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/**
 * `lstat`, with "not there" as `null`.
 *
 * Only ENOENT means absent. A permission error is not an absent install, and
 * reporting it as one would turn "I could not look" into "nothing to do".
 */
function lstatOrNull(target) {
  try {
    return fs.lstatSync(target);
  } catch (err) {
    if (err && err.code === 'ENOENT') return null;
    throw err;
  }
}

/**
 * Remove one directory entry without ever descending through it.
 *
 * Order matters. On Windows a junction reports `isSymbolicLink()`, and a
 * recursive remove on that path can walk into the target — which here is the
 * repository. Unlink the link; never touch the tree behind it.
 */
function removeEntry(target) {
  const info = lstatOrNull(target);
  if (!info) return 'absent';
  if (info.isSymbolicLink()) {
    fs.unlinkSync(target);
    return 'unlinked-link';
  }
  if (info.isDirectory()) {
    fs.rmSync(target, { recursive: true, force: true });
    return 'removed-dir';
  }
  fs.unlinkSync(target);
  return 'removed-file';
}

/**
 * Recursively list a tree, separating directories from files.
 *
 * Symlinks inside the tree are rejected rather than skipped: a mirror of a
 * symlink is ambiguous (copy the link, or copy what it points at?), and a
 * silently incomplete mirror is worse than a loud failure.
 */
function walk(root) {
  const dirs = [];
  const files = [];
  const stack = [''];
  while (stack.length) {
    const rel = stack.pop();
    const abs = rel ? path.join(root, rel) : root;
    for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
      const childRel = rel ? path.join(rel, entry.name) : entry.name;
      if (entry.isSymbolicLink()) {
        throw new Error(`refusing to mirror a symlink: ${path.join(root, childRel)}`);
      }
      if (entry.isDirectory()) {
        dirs.push(childRel);
        stack.push(childRel);
      } else if (entry.isFile()) {
        files.push(childRel);
      }
    }
  }
  return { dirs, files };
}

/** True when `target` is a link that currently resolves to `wanted`. */
function pointsAt(target, wanted) {
  const info = lstatOrNull(target);
  if (!info || !info.isSymbolicLink()) return false;
  try {
    // native resolves junctions and returns the on-disk spelling of the path.
    return samePath(fs.realpathSync.native(target), wanted);
  } catch {
    return false; // dangling: the repo moved or was deleted
  }
}

/**
 * True when `dir` is this project's checkout: the repository root is either the
 * directory itself or its parent, which is the layout everywhere in this repo.
 *
 * Deliberately *not* "some ancestor holds a .git". A dotfiles repository rooted
 * at $HOME would make every path under it look like a checkout — including the
 * stale installed copies this guard exists to reject.
 */
function isCheckout(dir) {
  return (
    fs.existsSync(path.join(dir, '.git')) ||
    fs.existsSync(path.join(path.dirname(dir), '.git'))
  );
}

function syncJunction(installPath, skillDir) {
  if (pointsAt(installPath, skillDir)) return { state: 'ok' };
  const replaced = removeEntry(installPath);
  fs.mkdirSync(path.dirname(installPath), { recursive: true });
  // 'junction' is Windows-only and needs no elevation; elsewhere a plain
  // directory symlink has the same property (resolved on every access).
  fs.symlinkSync(skillDir, installPath, process.platform === 'win32' ? 'junction' : 'dir');
  return { state: 'relinked', replaced };
}

function syncMirror(installPath, skillDir) {
  const { dirs, files } = walk(skillDir);
  const wanted = new Set(files);
  const counts = { files: files.length, linked: 0, replaced: 0, kept: 0, pruned: 0 };

  let rebuilt = null;
  // A junction here would be a hand-made mistake; walking through it and
  // pruning "extras" would delete repository files.
  if (lstatOrNull(installPath)?.isSymbolicLink()) rebuilt = removeEntry(installPath);
  if (rebuilt) {
    fs.mkdirSync(installPath, { recursive: true });
    counts.rebuilt = rebuilt;
  }

  const existing = walk(installPath);
  for (const rel of existing.files) {
    if (!wanted.has(rel)) {
      fs.unlinkSync(path.join(installPath, rel));
      counts.pruned += 1;
    }
  }
  const dirSet = new Set(dirs);
  for (const rel of existing.dirs.sort((a, b) => b.length - a.length)) {
    if (!dirSet.has(rel)) fs.rmdirSync(path.join(installPath, rel));
  }

  for (const rel of dirs) fs.mkdirSync(path.join(installPath, rel), { recursive: true });

  for (const rel of files) {
    const src = path.join(skillDir, rel);
    const dst = path.join(installPath, rel);
    const srcInfo = fs.statSync(src);
    const dstInfo = lstatOrNull(dst);
    // Equal inode *and* device: the hardlink survived. This is necessary, not
    // sufficient — NTFS may reuse a file id after a delete, so a copy that
    // happens to land on the same id reads as `kept`. Detecting that needs a
    // content hash. A plain copy, or a file git replaced, fails the test and is
    // relinked, which is the case that actually happens.
    if (dstInfo && !dstInfo.isSymbolicLink() && dstInfo.ino === srcInfo.ino && dstInfo.dev === srcInfo.dev) {
      counts.kept += 1;
      continue;
    }
    if (dstInfo) {
      fs.unlinkSync(dst);
      counts.replaced += 1;
    } else {
      counts.linked += 1;
    }
    fs.linkSync(src, dst);
  }

  const changed = counts.linked + counts.replaced + counts.pruned > 0 || Boolean(rebuilt);
  return { state: changed ? 'repaired' : 'ok', ...counts };
}

/**
 * Align every *existing* install position with `skillDir`.
 *
 * @param {{ skillDir?: string, home?: string, agents?: typeof AGENTS }} options
 * @returns {{ skillDir: string, home: string, results: object[] }}
 */
export function syncInstalls({ skillDir, home = os.homedir(), agents = AGENTS } = {}) {
  const resolvedHome = path.resolve(home);
  const candidate = path.resolve(
    skillDir ?? path.join(path.dirname(fileURLToPath(import.meta.url)), '..'),
  );
  // realpath collapses a junction install, so invoking the CLI through
  // ~/.claude/skills/... still lands on the repository. A hardlink mirror is a
  // real tree and stays where it is — which is why the guard below is needed.
  let resolvedSkill = candidate;
  try {
    resolvedSkill = fs.realpathSync.native(candidate);
  } catch {
    /* missing here; statSync below reports it */
  }
  const name = path.basename(resolvedSkill);

  // Syncing *from* an installed copy would point every other install at that
  // copy, building a chain through a mirror git can break. Refuse, unless the
  // path is genuinely a checkout (someone cloned the repo into place): then it
  // is the source of truth wherever it sits.
  for (const agent of agents) {
    const installPath = path.join(resolvedHome, agent.dir, name);
    if (samePath(installPath, resolvedSkill) && !isCheckout(resolvedSkill)) {
      const err = new Error(
        `refusing to sync from an installed copy: ${resolvedSkill}. ` +
          'Run this from the repository, or pass --skill-dir.',
      );
      err.usage = true;
      throw err;
    }
  }

  const info = fs.statSync(resolvedSkill); // throws if it is missing: the caller reports it
  if (!info.isDirectory()) throw new Error(`skill dir is not a directory: ${resolvedSkill}`);

  const results = [];

  // Check every position before touching any of them. Deciding this inside the
  // loop below would leave the earlier agents already relinked when the last
  // one turns out to overlap the source — a rejected run must be a no-op.
  for (const agent of agents) {
    const installPath = path.join(resolvedHome, agent.dir, name);
    if (!lstatOrNull(installPath) || samePath(installPath, resolvedSkill)) continue;
    if (contains(installPath, resolvedSkill) || contains(resolvedSkill, installPath)) {
      const err = new Error(
        `install position and source overlap: ${installPath} / ${resolvedSkill}`,
      );
      err.usage = true;
      throw err;
    }
  }

  for (const agent of agents) {
    const installPath = path.join(resolvedHome, agent.dir, name);
    // Absent means this agent never had the skill installed. Creating one is an
    // install, not a repair, and is out of scope.
    if (!lstatOrNull(installPath)) {
      results.push({ agent: agent.id, mode: agent.mode, installPath, state: 'not-installed' });
      continue;
    }
    // The repo cloned straight into an install position: it *is* the source, not
    // a copy. Replacing it with a link to itself would delete the checkout.
    if (samePath(installPath, resolvedSkill)) {
      results.push({ agent: agent.id, mode: agent.mode, installPath, state: 'is-source' });
      continue;
    }
    const outcome =
      agent.mode === 'junction'
        ? syncJunction(installPath, resolvedSkill)
        : syncMirror(installPath, resolvedSkill);
    results.push({ agent: agent.id, mode: agent.mode, installPath, ...outcome });
  }

  return { skillDir: resolvedSkill, home: resolvedHome, results };
}

/** `~/.claude/skills/x` when the path lives under home, the full path otherwise. */
function displayPath(home, target) {
  const rel = path.relative(home, target);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) return target;
  return `~/${rel.split(path.sep).join('/')}`;
}

/** Render a sync result as stderr lines: one per changed path, then a tally. */
export function formatSync({ home, results }) {
  const lines = [];
  const tally = { changed: 0, ok: 0, missing: 0 };
  for (const r of results) {
    const shown = displayPath(home, r.installPath);
    if (r.state === 'not-installed') {
      tally.missing += 1;
      continue;
    }
    if (r.state === 'ok' || r.state === 'is-source') {
      tally.ok += 1;
      continue;
    }
    tally.changed += 1;
    if (r.mode === 'mirror') {
      const bits = [`${r.files} files`];
      if (r.linked) bits.push(`linked ${r.linked}`);
      if (r.replaced) bits.push(`relinked ${r.replaced}`);
      if (r.pruned) bits.push(`pruned ${r.pruned}`);
      if (r.rebuilt) bits.push(`rebuilt (${r.rebuilt})`);
      lines.push(`self-heal: repaired ${shown} — ${bits.join(', ')}`);
    } else {
      lines.push(`self-heal: relinked ${shown} (was ${r.replaced})`);
    }
  }
  lines.push(
    `self-heal: ${tally.changed} changed, ${tally.ok} already correct, ${tally.missing} not installed`,
  );
  return lines;
}

const RUNNER_USAGE = `sync-installs — point the installed copies of this skill at the repository

Usage
  node scripts/sync-installs.mjs [--home <dir>] [--skill-dir <dir>]`;

/** An invocation mistake, which exits 64 like every other usage error here. */
function runnerUsage(message) {
  const err = new Error(message);
  err.usage = true;
  return err;
}

/** Strict, because a typo must not silently fall back to the real home. */
function parseRunnerArgs(argv) {
  const opts = { home: undefined, skillDir: undefined, help: false };
  const value = (i, label) => {
    const next = argv[i + 1];
    if (!next || next.startsWith('-')) throw runnerUsage(`${label} needs a directory`);
    return next;
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const eq = arg.indexOf('=');
    const flag = eq > 0 ? arg.slice(0, eq) : arg;
    const inline = eq > 0 ? arg.slice(eq + 1) : undefined;
    if (arg === '--help' || arg === '-h') {
      opts.help = true;
    } else if (flag === '--home' || flag === '--skill-dir') {
      const resolved = inline !== undefined ? inline : value(i, flag);
      if (!resolved) throw runnerUsage(`${flag} needs a directory`);
      if (inline === undefined) i += 1;
      if (flag === '--home') opts.home = resolved;
      else opts.skillDir = resolved;
    } else if (arg.startsWith('-')) {
      throw runnerUsage(`unknown option: ${arg}`);
    } else {
      throw runnerUsage(`unexpected argument: ${arg}`);
    }
  }
  return opts;
}

/**
 * Node resolves the main module through its realpath, so a plain string compare
 * says "not main" when the script is invoked through a junction — the most
 * likely way to reach this file from an install. Compare realpaths instead.
 */
function isMainModule() {
  if (!process.argv[1]) return false;
  try {
    const self = fs.realpathSync.native(fileURLToPath(import.meta.url));
    return samePath(self, fs.realpathSync.native(path.resolve(process.argv[1])));
  } catch {
    return false;
  }
}

if (isMainModule()) {
  try {
    const opts = parseRunnerArgs(process.argv.slice(2));
    if (opts.help) {
      process.stdout.write(`${RUNNER_USAGE}\n`);
    } else {
      const result = syncInstalls({ home: opts.home, skillDir: opts.skillDir });
      process.stdout.write(`${formatSync(result).join('\n')}\n`);
    }
  } catch (err) {
    process.stderr.write(`sync-installs: ${err.message}\n`);
    // Same split as the CLI: 64 is a bad invocation, 2 is "could not do it".
    process.exitCode = err && err.usage ? 64 : 2;
  }
}
