#!/usr/bin/env node
// worklab.mjs - one CLI for the pro workspace plan in todo.mac-setup.md
// (AeroSpace tiling, project workspaces, agents grid, macOS defaults, preflight, rollback).
//
// Zero dependencies, Node >= 18, macOS. Nothing runs until you call a command.
// Every command that changes something supports --dry-run (prints, changes nothing).
//
//   node worklab.mjs help
//
// Items marked VERIFY in the todo were written from memory of AeroSpace / macOS.
// They are marked VERIFY here too; check with `aerospace <cmd> --help` before relying on them.

import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import { homedir, platform } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { parseArgs } from 'node:util';

// ---------------------------------------------------------------- constants

const HOME = homedir();
const STATE_DIR = join(HOME, '.worklab');
const DEFAULTS_SNAPSHOT = join(STATE_DIR, 'defaults-snapshot.json');
const AERO_CONFIG = join(HOME, '.aerospace.toml');
const CHROME_PROFILES = join(HOME, '.chrome-dev');

const WORKSPACES = [
  { key: '0', name: '0-home', purpose: 'Empty desktop with widgets' },
  { key: '1', name: '1-proj-a', purpose: 'Project / worktree A: IDE, agent, test browser' },
  { key: '2', name: '2-proj-b', purpose: 'Project / worktree B' },
  { key: '3', name: '3-proj-c', purpose: 'Project / worktree C' },
  { key: 'a', name: 'agents', purpose: 'CLI agents grid' },
  { key: 'c', name: 'comms', purpose: 'Chat, notes, docs' },
];

// Section 2 of the todo. `rollback` is the pre-today value from the todo, used only
// when no snapshot exists. With a snapshot, rollback restores the real previous value.
const DEFAULTS = [
  { domain: 'com.apple.dock', key: 'autohide', type: '-bool', value: 'true', rollback: 'true' },
  { domain: 'com.apple.dock', key: 'autohide-delay', type: '-float', value: '0' },
  { domain: 'com.apple.dock', key: 'autohide-time-modifier', type: '-float', value: '0.15' },
  { domain: 'com.apple.dock', key: 'tilesize', type: '-int', value: '48', rollback: '127' },
  { domain: 'com.apple.dock', key: 'orientation', type: '-string', value: 'bottom', rollback: 'left' },
  { domain: 'com.apple.dock', key: 'mru-spaces', type: '-bool', value: 'false' },
  { domain: 'com.apple.WindowManager', key: 'EnableStandardClickToShowDesktop', type: '-bool', value: 'false' },
  // Optional, cosmetic. Skipped with --no-animations-tweak.
  { domain: 'NSGlobalDomain', key: 'NSAutomaticWindowAnimationsEnabled', type: '-bool', value: 'false', cosmetic: true },
  { domain: 'NSGlobalDomain', key: 'NSWindowResizeTime', type: '-float', value: '0.001', cosmetic: true },
];

// Floating rules from todo section 4. The BetterDisplay ID is the corrected one (VERIFY with `apps`).
const FLOAT_APPS = [
  'com.apple.systempreferences',
  'com.apple.finder',
  'com.apple.ActivityMonitor',
  'pro.betterdisplay.BetterDisplay',
];

// Config profiles: named, combinable setups for `config --profile a,b`.
// Later profiles override modifier/gap; float and route lists add up. Explicit flags win over profiles.
const PROFILES = {
  default: { desc: 'alt modifier, 6px gaps, system apps float' },
  intl: { desc: 'ctrl-alt modifier, so Option+letter still types special characters', modifier: 'ctrl-alt' },
  tight: { desc: '2px gaps for dense layouts (2x2 grids, 3-pane on a 1080p panel)', gap: 2 },
  roomy: { desc: '12px gaps, easier to see tile edges', gap: 12 },
  comms: {
    desc: 'Claude desktop and qLar always open on the comms workspace; PureMac floats',
    route: ['com.anthropic.claudefordesktop=comms', 'app.qlar.ai=comms'],
    float: ['com.puremac.app'],
  },
};

// Layout presets: what to launch and how to tile it. `worklab preset apply <name> [project paths]`.
// parts: ide | term | browser. layout: 3pane | pair | accordion | 2x2 | tiles.
// Add your own in ~/.worklab/presets.json (same shape; a user preset replaces a built-in of the same name).
const ALL_PARTS = ['ide', 'term', 'browser'];
const PRESETS = {
  home: { desc: 'Go to the empty 0-home workspace', projects: 0, workspaces: [], focus: '0-home' },
  solo: {
    desc: 'One project, 3-pane command center: IDE | agent over browser',
    projects: 1,
    workspaces: [{ ws: '1-proj-a', project: 0, parts: ALL_PARTS, layout: '3pane' }],
    focus: '1-proj-a',
  },
  dev: {
    desc: 'Dev desk: IDE | dev-stack terminal over test browser (hot reload), plus the agents grid',
    projects: 1,
    workspaces: [{ ws: '1-proj-a', project: 0, parts: ALL_PARTS, layout: '3pane' }],
    grid: true,
    focus: '1-proj-a',
  },
  focus: {
    desc: 'One project, IDE only in accordion (deep coding, one big editor)',
    projects: 1,
    workspaces: [{ ws: '1-proj-a', project: 0, parts: ['ide'], layout: 'accordion' }],
    focus: '1-proj-a',
  },
  pair: {
    desc: '50/50: IDE and live app (dev server already running)',
    projects: 1,
    workspaces: [{ ws: '1-proj-a', project: 0, parts: ['ide', 'browser'], layout: 'pair' }],
    focus: '1-proj-a',
  },
  dual: {
    desc: 'Two projects: A as 3-pane, B as IDE + dev server 50/50',
    projects: 2,
    workspaces: [
      { ws: '1-proj-a', project: 0, parts: ALL_PARTS, layout: '3pane' },
      { ws: '2-proj-b', project: 1, parts: ['ide', 'term'], layout: 'pair' },
    ],
    focus: '1-proj-a',
  },
  triple: {
    desc: 'Three projects: A as 3-pane, B and C as IDE + dev server 50/50 (heavy: watch swap)',
    projects: 3,
    workspaces: [
      { ws: '1-proj-a', project: 0, parts: ALL_PARTS, layout: '3pane' },
      { ws: '2-proj-b', project: 1, parts: ['ide', 'term'], layout: 'pair' },
      { ws: '3-proj-c', project: 2, parts: ['ide', 'term'], layout: 'pair' },
    ],
    focus: '1-proj-a',
  },
  agents: {
    desc: 'Only the tmux 2x2 agents grid (lightest way to run several agents)',
    projects: 0,
    workspaces: [],
    grid: true,
    focus: 'agents',
  },
  full: {
    desc: 'Project A 3-pane plus the agents grid (everything you use daily)',
    projects: 1,
    workspaces: [{ ws: '1-proj-a', project: 0, parts: ALL_PARTS, layout: '3pane' }],
    grid: true,
    focus: '1-proj-a',
  },
};

// ---------------------------------------------------------------- cli plumbing

const OPTIONS = {
  'dry-run': { type: 'boolean', short: 'n' },
  yes: { type: 'boolean', short: 'y' },
  help: { type: 'boolean', short: 'h' },
  // config
  profile: { type: 'string' }, // comma list of PROFILES
  wait: { type: 'string' }, // seconds to wait for windows in presets
  'claim-wait': { type: 'string' }, // seconds to wait for each launched window
  workspace: { type: 'string' }, // layout: switch to this workspace first
  force: { type: 'boolean' }, // layout: skip the exact-window-count guard
  modifier: { type: 'string' }, // alt | ctrl-alt | cmd-ctrl
  gap: { type: 'string' },
  float: { type: 'string', multiple: true }, // extra app ids to float
  route: { type: 'string', multiple: true }, // app-id=workspace
  print: { type: 'boolean' },
  // defaults
  'no-animations-tweak': { type: 'boolean' },
  // ws / grid
  ide: { type: 'string' },
  term: { type: 'string' },
  cmd: { type: 'string' },
  port: { type: 'string' },
  browser: { type: 'string' },
  'no-browser': { type: 'boolean' },
  'no-ide': { type: 'boolean' },
  'no-stack': { type: 'boolean' }, // ignore a project's dev-stack script
  agents: { type: 'string' }, // comma list for the 4 grid panes
  session: { type: 'string' },
  // rollback
  uninstall: { type: 'boolean' },
};

let flags = {};
let dryRun = false;

const c = {
  dim: (s) => `\x1b[2m${s}\x1b[0m`,
  red: (s) => `\x1b[31m${s}\x1b[0m`,
  green: (s) => `\x1b[32m${s}\x1b[0m`,
  yellow: (s) => `\x1b[33m${s}\x1b[0m`,
  bold: (s) => `\x1b[1m${s}\x1b[0m`,
};
const log = (s = '') => console.log(s);
const info = (s) => console.log(`${c.bold('==>')} ${s}`);
const ok = (s) => console.log(`${c.green('ok')}   ${s}`);
const warn = (s) => console.log(`${c.yellow('warn')} ${s}`);
const fail = (s) => console.log(`${c.red('FAIL')} ${s}`);

class UserError extends Error {}

function fmt(cmd, args) {
  return [cmd, ...args].map((a) => (/[\s"'$`]/.test(a) ? JSON.stringify(a) : a)).join(' ');
}

/** Read-only command. Always runs, even in dry-run. Returns stdout or null on failure. */
function read(cmd, args = [], { allowFail = true } = {}) {
  try {
    return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  } catch (e) {
    if (!allowFail) throw new UserError(`${fmt(cmd, args)} failed: ${(e.stderr || e.message).toString().trim()}`);
    return null;
  }
}

/** Mutating command. In dry-run it only prints. Returns true if it ran and succeeded. */
function run(cmd, args = [], { allowFail = false, quiet = false, silent = false } = {}) {
  if (dryRun) {
    log(c.dim(`[dry-run] ${fmt(cmd, args)}`));
    return true;
  }
  if (!quiet) log(c.dim(`$ ${fmt(cmd, args)}`));
  const r = spawnSync(cmd, args, { stdio: silent ? 'ignore' : 'inherit' });
  if (r.error || r.status !== 0) {
    if (allowFail) return false;
    throw new UserError(`${fmt(cmd, args)} failed${r.error ? `: ${r.error.message}` : ` (exit ${r.status})`}`);
  }
  return true;
}

const has = (bin) => read('/usr/bin/which', [bin]) !== null;

function requireMac() {
  if (platform() !== 'darwin') throw new UserError('This command only works on macOS.');
}

function requireAerospace() {
  if (!has('aerospace')) {
    throw new UserError('aerospace not found. Run: node worklab.mjs install');
  }
}

async function confirm(question) {
  if (flags.yes || dryRun) return true;
  if (!process.stdin.isTTY) throw new UserError(`"${question}" needs confirmation. Re-run with --yes (or --dry-run to preview).`);
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const a = (await rl.question(`${question} [y/N] `)).trim().toLowerCase();
  rl.close();
  return a === 'y' || a === 'yes';
}

const sleep = (s) => {
  if (dryRun || process.env.WORKLAB_NO_SLEEP) return;
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, s * 1000);
};

// ---------------------------------------------------------------- doctor (todo sections 0, 1, 9)

function cmdDoctor() {
  info('Preflight (todo sections 1 and 9)');
  let problems = 0;

  // Disk: keep >= 20% free on the data volume
  const df = read('df', ['-k', '/System/Volumes/Data']) ?? read('df', ['-k', '/']);
  if (df) {
    const cols = df.split('\n').pop().trim().split(/\s+/);
    const total = Number(cols[1]);
    const avail = Number(cols[3]);
    const pct = (avail / total) * 100;
    const gib = (avail / 1024 / 1024).toFixed(1);
    if (pct >= 20) ok(`disk free ${pct.toFixed(0)}% (${gib} GiB)`);
    else {
      fail(`disk free ${pct.toFixed(0)}% (${gib} GiB), want >= 20%. See mac-setup.md section 5 for cleanup.`);
      problems++;
    }
  }

  // Swap: near 0 after restart, under ~2 GB in daily use
  const swap = read('sysctl', ['-n', 'vm.swapusage']);
  if (swap) {
    const used = /used = ([\d.]+)([MG])/.exec(swap);
    const usedMb = used ? Number(used[1]) * (used[2] === 'G' ? 1024 : 1) : 0;
    if (usedMb < 2048) ok(`swap used ${used ? used[1] + used[2] : '0'} (under ~2 GB)`);
    else {
      fail(`swap used ${used[1]}${used[2]}; restart and re-check, or close heavy apps`);
      problems++;
    }
  }

  // Heavy-process budget: top memory users
  const ps = read('ps', ['-axo', 'rss=,comm=']);
  if (ps) {
    const rows = ps
      .split('\n')
      .map((l) => l.trim().match(/^(\d+)\s+(.*)$/))
      .filter(Boolean)
      .map((m) => ({ mb: Math.round(Number(m[1]) / 1024), name: m[2].split('/').pop() }));
    const byName = new Map();
    for (const r of rows) byName.set(r.name, (byName.get(r.name) ?? 0) + r.mb);
    const top = [...byName.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
    log(`     top memory: ${top.map(([n, mb]) => `${n} ${mb}MB`).join(', ')}`);
    const ides = ['Cursor', 'Code', 'Zed', 'Electron'].filter((n) => byName.has(n));
    if (ides.length > 1) warn(`more than one IDE family running (${ides.join(', ')}); budget says one`);
    const pw = rows.filter((r) => /playwright|chrome-headless-shell/i.test(r.name)).length;
    if (pw > 2) warn(`${pw} Playwright/headless processes; budget says at most 2 workers`);
  }

  // Conflicting window managers
  for (const app of ['Rectangle', 'Magnet', 'Amethyst', 'yabai']) {
    if (read('pgrep', ['-xi', app])) {
      warn(`${app} is running; do not run it together with AeroSpace`);
      problems++;
    }
  }

  // Tooling
  for (const bin of ['brew', 'aerospace', 'tmux']) {
    if (has(bin)) ok(`${bin} found`);
    else warn(`${bin} not found${bin === 'aerospace' ? ' (run: install)' : bin === 'tmux' ? ' (brew install tmux, needed for grid)' : ''}`);
  }

  log();
  log(problems ? c.yellow(`${problems} issue(s) to look at before continuing.`) : c.green('Preflight clean.'));
  return problems;
}

// ---------------------------------------------------------------- defaults (section 2)

function readDefault(domain, key) {
  const v = read('defaults', ['read', domain, key]);
  return v === null ? null : v;
}

async function cmdDefaults(sub = 'apply') {
  requireMac();
  if (sub === 'apply') {
    const list = DEFAULTS.filter((d) => !(flags['no-animations-tweak'] && d.cosmetic));
    info('macOS defaults to write:');
    for (const d of list) log(`     ${d.domain} ${d.key} = ${d.value}   ${c.dim(`(now: ${readDefault(d.domain, d.key) ?? 'unset'})`)}`);
    if (!(await confirm('Apply these and restart the Dock?'))) return log('Cancelled.');

    // Snapshot before touching anything, but never overwrite an existing snapshot:
    // the first one holds the true original values.
    if (!dryRun) {
      mkdirSync(STATE_DIR, { recursive: true });
      if (!existsSync(DEFAULTS_SNAPSHOT)) {
        const snap = DEFAULTS.map((d) => ({ domain: d.domain, key: d.key, previous: readDefault(d.domain, d.key) }));
        writeFileSync(DEFAULTS_SNAPSHOT, JSON.stringify(snap, null, 2));
        ok(`snapshot saved to ${DEFAULTS_SNAPSHOT}`);
      } else warn(`keeping existing snapshot ${DEFAULTS_SNAPSHOT}`);
    }
    for (const d of list) run('defaults', ['write', d.domain, d.key, d.type, d.value]);
    run('killall', ['Dock'], { allowFail: true });
    log('Manual (System Settings): Mission Control -> turn off "Automatically rearrange Spaces based on most recent use" (the mru-spaces key above does the same).');
    log('Manual: Desktop & Dock -> "Click wallpaper to reveal desktop" -> Only in Stage Manager; Stage Manager off.');
    return;
  }

  if (sub === 'rollback') {
    const snapshot = existsSync(DEFAULTS_SNAPSHOT) ? JSON.parse(readFileSync(DEFAULTS_SNAPSHOT, 'utf8')) : null;
    info(snapshot ? `Restoring values from ${DEFAULTS_SNAPSHOT}` : 'No snapshot found; using the fixed rollback values from the todo (Dock only).');
    if (!(await confirm('Restore previous macOS defaults and restart the Dock?'))) return log('Cancelled.');
    for (const d of DEFAULTS) {
      if (snapshot) {
        const prev = snapshot.find((s) => s.domain === d.domain && s.key === d.key)?.previous;
        if (prev === null || prev === undefined) run('defaults', ['delete', d.domain, d.key], { allowFail: true });
        else run('defaults', ['write', d.domain, d.key, d.type, normalizeBool(d.type, prev)]);
      } else if (d.rollback !== undefined) {
        run('defaults', ['write', d.domain, d.key, d.type, d.rollback]);
      } else if (d.cosmetic) {
        run('defaults', ['delete', d.domain, d.key], { allowFail: true });
      }
    }
    run('killall', ['Dock'], { allowFail: true });
    return;
  }
  throw new UserError(`defaults: unknown subcommand "${sub}" (use apply | rollback)`);
}

// `defaults read` prints booleans as 1/0; `defaults write -bool` wants true/false.
function normalizeBool(type, v) {
  if (type !== '-bool') return String(v);
  return v === '1' || v === 'true' ? 'true' : 'false';
}

// ---------------------------------------------------------------- install (section 3, 8)

async function cmdInstall(what = 'aerospace') {
  requireMac();
  if (!has('brew')) throw new UserError('Homebrew not found. Install it from https://brew.sh first.');
  if (what === 'aerospace') {
    if (has('aerospace')) ok('aerospace already installed');
    else {
      if (!(await confirm('brew install --cask nikitabobko/tap/aerospace ?'))) return log('Cancelled.');
      run('brew', ['install', '--cask', 'nikitabobko/tap/aerospace']);
    }
    run('open', ['-a', 'AeroSpace'], { allowFail: true });
    log();
    log('Manual step: System Settings -> Privacy & Security -> Accessibility -> enable AeroSpace.');
    log('Then: node worklab.mjs apps    (copy your IDE / browser / terminal app IDs for --route / --float)');
    return;
  }
  if (what === 'betterdisplay') {
    log('Phase 4 is optional. Only do it if the panel is large (todo decision 0) and sections 1-7 work.');
    if (!(await confirm('brew install --cask betterdisplay ?'))) return log('Cancelled.');
    run('brew', ['install', '--cask', 'betterdisplay']);
    log('Manual: create a 16:9 virtual screen, enable HiDPI, mirror the physical panel to it, start at 2560x1440 (HiDPI). VERIFY menu names.');
    log('Then watch `sysctl vm.swapusage` and WindowServer memory for a day. If swap climbs: disconnect the virtual screen, mirroring off.');
    return;
  }
  throw new UserError(`install: unknown target "${what}" (use aerospace | betterdisplay)`);
}

function cmdApps() {
  requireAerospace();
  info('Running apps as AeroSpace sees them (use these ids for --route / --float):');
  const out = read('aerospace', ['list-apps']);
  log(out ?? c.dim('(aerospace returned nothing; is it running and enabled in Accessibility?)'));
}

// ---------------------------------------------------------------- config (section 4)

const MODIFIERS = { alt: 'alt', 'ctrl-alt': 'ctrl-alt', 'cmd-ctrl': 'cmd-ctrl' };

function buildConfig({ mod, gap, extraFloat, routes }) {
  const b = (k, action) => `${mod}-${k} = ${action}`;
  const q = (s) => `'${s}'`;
  const lines = [];
  const push = (...l) => lines.push(...l);

  push(
    '# Generated by worklab.mjs. Edit freely; re-generate with: node worklab.mjs config',
    `# modifier: ${mod}`,
    '',
    'config-version = 2',
    '',
    'start-at-login = true',
    // Version 2 only lists non-empty workspaces unless they are persistent.
    `persistent-workspaces = [${WORKSPACES.map((w) => `'${w.name}'`).join(', ')}]`,
    '',
    'enable-normalization-flatten-containers = true',
    'enable-normalization-opposite-orientation-for-nested-containers = true',
    '',
    'accordion-padding = 30',
    "default-root-container-layout = 'tiles'",
    "default-root-container-orientation = 'auto'",
    '',
    '[gaps]',
    `inner.horizontal = ${gap}`,
    `inner.vertical   = ${gap}`,
    `outer.top        = ${gap}`,
    `outer.bottom     = ${gap}`,
    `outer.left       = ${gap}`,
    `outer.right      = ${gap}`,
    '',
    '[mode.main.binding]',
    '# Workspaces',
  );
  for (const w of WORKSPACES) push(b(w.key, q(`workspace ${w.name}`)));
  push(b('tab', q('workspace-back-and-forth')), '', '# Move window to workspace');
  for (const w of WORKSPACES) push(b(`shift-${w.key}`, q(`move-node-to-workspace ${w.name}`)));
  push(
    '',
    '# Focus / move (vim keys)',
    b('h', q('focus left')),
    b('j', q('focus down')),
    b('k', q('focus up')),
    b('l', q('focus right')),
    b('shift-h', q('move left')),
    b('shift-j', q('move down')),
    b('shift-k', q('move up')),
    b('shift-l', q('move right')),
    '',
    '# Nest a window with its neighbour (builds 3-pane and 2x2 layouts). Replaces split bindings.',
    b('shift-left', q('join-with left')),
    b('shift-down', q('join-with down')),
    b('shift-up', q('join-with up')),
    b('shift-right', q('join-with right')),
    '',
    '# Layout (VERIFY slash / comma key names)',
    b('slash', q('layout tiles horizontal vertical')),
    b('comma', q('layout accordion horizontal vertical')),
    b('f', q('layout floating tiling')),
    b('shift-f', q('flatten-workspace-tree')),
    '',
    '# Resize',
    b('minus', q('resize smart -50')),
    b('equal', q('resize smart +50')),
    '',
    '# Service mode',
    b('r', q('mode service')),
    '',
    '[mode.service.binding]',
    "esc = ['reload-config', 'mode main']",
    "r = ['flatten-workspace-tree', 'mode main']",
    "b = ['balance-sizes', 'mode main']",
    "f = ['layout floating tiling', 'mode main']",
    "enter = 'mode main'",
    '',
    '# Floating rules: dialogs and utilities never tile.',
  );
  for (const id of [...FLOAT_APPS, ...extraFloat]) {
    push('[[on-window-detected]]', `if.app-id = ${q(id)}`, "run = 'layout floating'", '');
  }
  if (routes.length) push('# Auto-route apps to their home workspace');
  for (const { id, ws } of routes) {
    push('[[on-window-detected]]', `if.app-id = ${q(id)}`, `run = ${q(`move-node-to-workspace ${ws}`)}`, '');
  }
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
}

function mergeProfiles(spec) {
  const out = { route: [], float: [] };
  for (const name of (spec ?? '').split(',').map((s) => s.trim()).filter(Boolean)) {
    const p = PROFILES[name];
    if (!p) throw new UserError(`unknown profile "${name}". Known: ${Object.keys(PROFILES).join(', ')}`);
    if (p.modifier) out.modifier = p.modifier;
    if (p.gap !== undefined) out.gap = p.gap;
    out.route.push(...(p.route ?? []));
    out.float.push(...(p.float ?? []));
  }
  return out;
}

function cmdProfiles() {
  info('Config profiles (use: config --profile a,b)');
  for (const [name, p] of Object.entries(PROFILES)) log(`  ${name.padEnd(8)} ${p.desc}`);
}

async function cmdConfig() {
  const prof = mergeProfiles(flags.profile);
  const mod = MODIFIERS[flags.modifier ?? prof.modifier ?? 'alt'];
  if (!mod) throw new UserError(`--modifier must be one of: ${Object.keys(MODIFIERS).join(', ')}`);
  const gap = Number(flags.gap ?? prof.gap ?? 6);
  if (!Number.isInteger(gap) || gap < 0 || gap > 64) throw new UserError('--gap must be an integer 0-64');

  const wsNames = new Set(WORKSPACES.map((w) => w.name));
  const routes = [...prof.route, ...(flags.route ?? [])].map((r) => {
    const [id, ws] = r.split('=');
    if (!id || !ws) throw new UserError(`--route expects app-id=workspace, got "${r}"`);
    if (!wsNames.has(ws)) throw new UserError(`--route workspace "${ws}" is not one of: ${[...wsNames].join(', ')}`);
    return { id, ws };
  });

  const text = buildConfig({ mod, gap, extraFloat: [...prof.float, ...(flags.float ?? [])], routes });
  if (flags.print) return process.stdout.write(text);

  if (mod === 'alt') warn('Alt+letter is now global: Option+letter stops typing special characters on non-US layouts. Use --modifier ctrl-alt if you need them.');

  if (existsSync(AERO_CONFIG)) {
    const existing = readFileSync(AERO_CONFIG, 'utf8');
    if (existing === text) return ok(`${AERO_CONFIG} already up to date`);
    if (!(await confirm(`Overwrite ${AERO_CONFIG}? (a timestamped backup is kept)`))) return log('Cancelled.');
    const backup = `${AERO_CONFIG}.bak-${new Date().toISOString().replace(/[:.]/g, '-')}`;
    if (dryRun) log(c.dim(`[dry-run] backup -> ${backup}`));
    else {
      copyFileSync(AERO_CONFIG, backup);
      ok(`backup: ${backup}`);
    }
  }
  if (dryRun) log(c.dim(`[dry-run] write ${AERO_CONFIG} (${text.split('\n').length} lines)`));
  else {
    writeFileSync(AERO_CONFIG, text);
    ok(`wrote ${AERO_CONFIG}`);
  }
  if (has('aerospace')) run('aerospace', ['reload-config'], { allowFail: true });
  else warn('aerospace not installed yet; config will load on first start');
}

// ---------------------------------------------------------------- layouts (section 6)

const aero = (...args) => run('aerospace', args, { allowFail: true, quiet: true });

function focusFarLeft(times = 6) {
  for (let i = 0; i < times; i++) aero('focus', 'left');
}

function layoutFlatTiles() {
  aero('flatten-workspace-tree');
  aero('layout', 'tiles', 'horizontal');
}

// Layouts that nest windows need exactly this many windows, or they would rearrange the wrong ones.
const EXACT_WINDOWS = { '3pane': 3, '2x2': 4 };

function cmdLayout(name) {
  requireAerospace();
  if (flags.workspace) {
    run('aerospace', ['workspace', resolveWs(flags.workspace).name], { quiet: true, silent: true });
  }
  const focused = read('aerospace', ['list-workspaces', '--focused']) ?? '?';
  const count = Number(read('aerospace', ['list-windows', '--workspace', 'focused', '--count']) ?? 0);
  const need = EXACT_WINDOWS[name];
  if (need && !dryRun && !flags.force && count !== need) {
    throw new UserError(
      `layout ${name} needs exactly ${need} windows, but the focused workspace "${focused}" has ${count}. ` +
        `Nothing changed. Switch workspace (or pass --workspace <name>), or --force to run anyway.`,
    );
  }
  info(`layout ${name} on workspace "${focused}" (${count} window${count === 1 ? '' : 's'})`);
  switch (name) {
    case '3pane': {
      // [IDE][Agent][Browser] -> IDE | (Agent over Browser)
      layoutFlatTiles();
      focusFarLeft();
      aero('focus', 'right'); // the agent
      aero('join-with', 'right'); // agent + browser become a vertical stack
      aero('balance-sizes');
      log('Done. Tune with the resize keys, or: node worklab.mjs layout balance');
      break;
    }
    case '2x2': {
      // [1][2][3][4] -> (1 over 2) | (3 over 4)
      layoutFlatTiles();
      focusFarLeft();
      aero('focus', 'right'); // window 2
      aero('join-with', 'left'); // [1,2] [3] [4]
      aero('focus', 'right'); // 3
      aero('focus', 'right'); // 4
      aero('join-with', 'left'); // [1,2] [3,4]
      aero('balance-sizes');
      break;
    }
    case 'pair':
      layoutFlatTiles();
      aero('balance-sizes');
      break;
    case 'accordion':
      aero('layout', 'accordion', 'horizontal', 'vertical');
      break;
    case 'tiles':
      aero('layout', 'tiles', 'horizontal', 'vertical');
      break;
    case 'flatten':
      aero('flatten-workspace-tree');
      break;
    case 'balance':
      aero('balance-sizes');
      break;
    default:
      throw new UserError('layout: use 3pane | 2x2 | pair | accordion | tiles | flatten | balance');
  }
}

// ---------------------------------------------------------------- project workspace (section 7: devws)

function launchTerminal(term, path, cmd) {
  const shellCmd = `cd ${shq(path)} && ${cmd}; exec zsh`;
  const t = term.toLowerCase();
  if (t === 'ghostty') {
    // VERIFY Ghostty flags with `ghostty --help`
    return run('open', ['-na', 'Ghostty', '--args', `--working-directory=${path}`, '-e', 'zsh', '-c', `${cmd}; exec zsh`]);
  }
  if (t === 'iterm' || t === 'iterm2') {
    // A new window, then type the command into its shell (a `command "..."` string loses its quoting).
    return run('osascript', [
      '-e', 'tell application "iTerm"',
      '-e', 'set w to (create window with default profile)',
      '-e', `tell current session of w to write text "${applescriptEscape(shellCmd)}"`,
      '-e', 'end tell',
    ]);
  }
  if (t === 'terminal') {
    return run('osascript', ['-e', `tell application "Terminal" to do script "${applescriptEscape(shellCmd)}"`, '-e', 'tell application "Terminal" to activate']);
  }
  throw new UserError(`Unknown terminal "${term}" (use Ghostty | iTerm | Terminal)`);
}

const shq = (s) => `'${s.replace(/'/g, `'\\''`)}'`;
const applescriptEscape = (s) => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"');

function resolveWs(arg) {
  const ws = WORKSPACES.find((w) => w.name === arg || w.key === arg);
  if (!ws) throw new UserError(`unknown workspace "${arg}". Known: ${WORKSPACES.map((w) => `${w.key}/${w.name}`).join(', ')}`);
  return ws;
}

function resolveDir(p) {
  const path = resolve(p.replace(/^~(?=$|\/)/, HOME));
  if (!existsSync(path)) throw new UserError(`path not found: ${path}`);
  return path;
}

// Repos that ship a dev-stack script: the desk starts it instead of `npm run dev`, and the browser opens on its port.
// os-lab: scripts/ux/dev-stack.sh dev (Astro :4321, console :5050). qLar: agents-app/scripts/dev-stack.sh start (astro dev :8140).
const DEV_STACKS = [
  { rel: 'scripts/ux/dev-stack.sh', start: 'dev', port: () => process.env.OSLAB_UI_PORT ?? '4321' },
  { rel: 'agents-app/scripts/dev-stack.sh', start: 'start', port: () => process.env.QLAR_DEV_PORT ?? '8140' },
];

/** The dev-stack script of a project folder, or null. `--no-stack` turns detection off. */
function detectStack(path) {
  if (flags['no-stack']) return null;
  for (const d of DEV_STACKS) {
    const script = join(path, d.rel);
    if (existsSync(script)) return { script, cmd: `${shq(script)} ${d.start}; ${shq(script)} status`, port: d.port() };
  }
  return null;
}

/** Launch the requested parts on a workspace, in the order IDE, terminal, browser. Returns how many windows it expects. */
function launchProject(ws, path, parts = ALL_PARTS) {
  const ide = flags.ide ?? process.env.DEV_IDE ?? 'Cursor';
  const term = flags.term ?? process.env.TERM_APP ?? 'Ghostty';
  const stack = detectStack(path);
  const cmd = flags.cmd ?? stack?.cmd ?? 'npm run dev';
  const port = flags.port ?? stack?.port ?? '3000';
  if (stack && !flags.cmd) info(`dev stack found: ${stack.script} (browser on :${port}; --no-stack to use npm run dev)`);
  if (!/^\d+$/.test(port)) throw new UserError('--port must be a number');
  const browser = flags.browser ?? 'Google Chrome';

  info(`Workspace ${ws.name}: ${path} [${parts.join(', ')}]`);
  run('aerospace', ['workspace', ws.name]);
  let expected = 0;

  if (parts.includes('ide')) {
    claimWindows(ws.name, 'ide', () => run('open', ['-a', ide, path]));
    expected++;
  }
  if (parts.includes('term')) {
    claimWindows(ws.name, 'terminal', () => launchTerminal(term, path, cmd));
    expected++;
  }
  if (parts.includes('browser')) {
    // Per-workspace profile under ~/.chrome-dev (not /tmp), so logins survive reboots.
    const profile = join(CHROME_PROFILES, ws.name);
    if (dryRun) log(c.dim(`[dry-run] mkdir -p ${profile}`));
    else mkdirSync(profile, { recursive: true });
    claimWindows(ws.name, 'browser', () =>
      run('open', ['-na', browser, '--args', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', `http://localhost:${port}`]),
    );
    expected++;
  }
  return expected;
}

const windowIds = () => new Set((read('aerospace', ['list-windows', '--all', '--format', '%{window-id}']) ?? '').split('\n').map((s) => s.trim()).filter(Boolean));

/**
 * Run `launch`, wait for the window(s) it creates, and move them to `wsName` by window id.
 * Launching an app can pull focus to that app's existing window on another workspace, and
 * AeroSpace follows focus, so "open on the focused workspace" is not reliable.
 */
function claimWindows(wsName, label, launch) {
  if (dryRun) {
    launch();
    log(c.dim(`[dry-run] move new ${label} window(s) to ${wsName}`));
    return [];
  }
  const before = windowIds();
  launch();
  const timeout = Number(flags['claim-wait'] ?? 12);
  const start = Date.now();
  let fresh = [];
  while ((Date.now() - start) / 1000 < timeout) {
    fresh = [...windowIds()].filter((id) => !before.has(id));
    if (fresh.length) break;
    sleep(0.5);
  }
  if (!fresh.length) {
    warn(`${label}: no new window appeared (the app may have reused an existing window); nothing moved`);
    return [];
  }
  sleep(0.5); // catch windows that open a beat later
  fresh = [...windowIds()].filter((id) => !before.has(id));
  for (const id of fresh) run('aerospace', ['move-node-to-workspace', '--window-id', id, wsName], { allowFail: true, quiet: true, silent: true });
  // Focus the window itself, not just the workspace: otherwise macOS focus can slide back to the
  // app's older window on another workspace and AeroSpace follows it there.
  run('aerospace', ['focus', '--window-id', fresh.at(-1)], { allowFail: true, quiet: true, silent: true });
  run('aerospace', ['workspace', wsName], { quiet: true, silent: true });
  return fresh;
}

function cmdWs(wsArg, pathArg) {
  requireAerospace();
  if (!wsArg || !pathArg) throw new UserError('usage: worklab ws <workspace> <project-path> [--cmd "npm run dev"] [--port 3000] [--ide Cursor] [--term Ghostty]');
  const ws = resolveWs(wsArg);
  const path = resolveDir(pathArg);
  const parts = ALL_PARTS.filter((p) => !(p === 'ide' && flags['no-ide']) && !(p === 'browser' && flags['no-browser']));
  launchProject(ws, path, parts);
  log(`Workspace ${ws.name} launched. Windows open as [IDE][Terminal][Browser]; when all are up run:`);
  log(c.bold('  node worklab.mjs layout 3pane'));
}

// ---------------------------------------------------------------- presets

function loadPresets() {
  const file = join(STATE_DIR, 'presets.json');
  if (!existsSync(file)) return PRESETS;
  let user;
  try {
    user = JSON.parse(readFileSync(file, 'utf8'));
  } catch (e) {
    throw new UserError(`${file} is not valid JSON: ${e.message}`);
  }
  const layouts = new Set(['3pane', '2x2', 'pair', 'accordion', 'tiles']);
  for (const [name, p] of Object.entries(user)) {
    if (!p || typeof p !== 'object' || !Array.isArray(p.workspaces ?? [])) throw new UserError(`${file}: preset "${name}" needs a workspaces array`);
    for (const e of p.workspaces ?? []) {
      resolveWs(e.ws);
      if (e.layout && !layouts.has(e.layout)) throw new UserError(`${file}: preset "${name}" has unknown layout "${e.layout}"`);
      for (const part of e.parts ?? ALL_PARTS) if (!ALL_PARTS.includes(part)) throw new UserError(`${file}: preset "${name}" has unknown part "${part}"`);
    }
  }
  return { ...PRESETS, ...Object.fromEntries(Object.entries(user).map(([n, p]) => [n, { projects: 0, workspaces: [], ...p }])) };
}

function waitForWindows(wsName, expected) {
  if (dryRun || expected === 0) return expected;
  const timeout = Number(flags.wait ?? 20);
  const start = Date.now();
  let count = 0;
  for (;;) {
    count = Number(read('aerospace', ['list-windows', '--workspace', wsName, '--count']) ?? 0);
    if (count >= expected || (Date.now() - start) / 1000 >= timeout) return count;
    sleep(0.5);
  }
}

function cmdPreset(sub = 'list', name, ...paths) {
  const presets = loadPresets();
  if (sub === 'list') {
    info('Layout presets (apply: preset apply <name> [project paths])');
    for (const [n, p] of Object.entries(presets)) log(`  ${n.padEnd(8)} ${String(p.projects ?? 0)} path(s)  ${p.desc ?? ''}`);
    return;
  }
  if (!['show', 'apply'].includes(sub)) throw new UserError('preset: use list | show <name> | apply <name> [paths...]');
  const p = presets[name];
  if (!p) throw new UserError(`unknown preset "${name}". Known: ${Object.keys(presets).join(', ')}`);

  if (sub === 'show') {
    info(`${name}: ${p.desc ?? ''}`);
    log(JSON.stringify(p, null, 2));
    return;
  }

  requireAerospace();
  if (paths.length < (p.projects ?? 0)) throw new UserError(`preset "${name}" needs ${p.projects} project path(s), got ${paths.length}`);
  const dirs = paths.map(resolveDir);
  info(`Preset ${name}: ${p.desc ?? ''}`);

  for (const e of p.workspaces ?? []) {
    const ws = resolveWs(e.ws);
    const parts = e.parts ?? ALL_PARTS;
    const expected = launchProject(ws, dirs[e.project ?? 0], parts);
    const got = waitForWindows(ws.name, expected);
    if (got < expected) warn(`${ws.name}: ${got} of ${expected} windows appeared; layout may be off (try: layout flatten)`);
    if (e.layout) {
      if (e.layout === '3pane' && got < 3) warn(`${ws.name}: skipping 3pane, needs 3 windows`);
      else {
        run('aerospace', ['workspace', ws.name], { quiet: true });
        try {
          cmdLayout(e.layout);
        } catch (err) {
          if (!(err instanceof UserError)) throw err;
          warn(`${ws.name}: layout skipped. ${err.message}`);
        }
      }
    }
  }
  if (p.grid) buildGrid(dirs[0] ?? HOME);
  if (p.focus) run('aerospace', ['workspace', resolveWs(p.focus).name]);
  ok(`preset ${name} applied`);
}

// ---------------------------------------------------------------- agents grid (section 7: devgrid)

function cmdGrid(dirArg) {
  requireAerospace();
  buildGrid(resolveDir(dirArg ?? HOME));
}

function buildGrid(dir) {
  if (!has('tmux')) throw new UserError('tmux not found: brew install tmux');

  // 4 panes. Default: claude, codex, two plain shells. Local models are opt-in (they compete for RAM):
  //   --agents "claude,codex,aider,ollama run codellama"   use an empty entry for a plain shell
  const agents = (flags.agents ?? 'claude,codex,,').split(',').map((s) => s.trim());
  while (agents.length < 4) agents.push('');
  if (agents.length > 4) throw new UserError('--agents takes at most 4 comma separated commands');
  const session = flags.session ?? 'agents';
  const term = flags.term ?? process.env.TERM_APP ?? 'Ghostty';

  info(`Agents grid in tmux session "${session}" (${dir})`);
  run('aerospace', ['workspace', 'agents']);
  run('tmux', ['kill-session', '-t', session], { allowFail: true, quiet: true, silent: true });
  run('tmux', ['new-session', '-d', '-s', session, '-c', dir]);
  run('tmux', ['split-window', '-h', '-t', `${session}:0`, '-c', dir]);
  run('tmux', ['split-window', '-v', '-t', `${session}:0.0`, '-c', dir]);
  run('tmux', ['split-window', '-v', '-t', `${session}:0.2`, '-c', dir]);
  run('tmux', ['select-layout', '-t', `${session}:0`, 'tiled']);
  agents.forEach((a, i) => {
    if (a) run('tmux', ['send-keys', '-t', `${session}:0.${i}`, a, 'C-m']);
  });

  const attach = `tmux attach -t ${session}`;
  const t = term.toLowerCase();
  claimWindows('agents', 'tmux terminal', () => {
    if (t === 'ghostty') run('open', ['-na', 'Ghostty', '--args', '-e', 'tmux', 'attach', '-t', session]);
    else launchTerminal(term, dir, attach);
  });
  log('One tmux window replaces four loose terminals. Detach with ctrl-b d; kill with: tmux kill-session -t ' + session);
}

// ---------------------------------------------------------------- verify (section 9)

function cmdVerify() {
  info('Verify (todo section 9)');
  const check = (label, got, want) => {
    if (got === null) return warn(`${label}: not set`);
    got === want ? ok(`${label} = ${got}`) : fail(`${label} = ${got}, expected ${want}`);
  };
  if (platform() === 'darwin') {
    check('dock mru-spaces', read('defaults', ['read', 'com.apple.dock', 'mru-spaces']), '0');
    check('dock autohide', read('defaults', ['read', 'com.apple.dock', 'autohide']), '1');
  }
  cmdDoctor();
  if (has('aerospace')) {
    log();
    log(c.bold('workspaces:'));
    log(read('aerospace', ['list-workspaces', '--all']) ?? c.dim('(unavailable: is AeroSpace running?)'));
    log(c.bold('windows:'));
    log(read('aerospace', ['list-windows', '--all']) ?? c.dim('(unavailable)'));
  }
}

// ---------------------------------------------------------------- rollback (section 10)

async function cmdRollback() {
  info('Rollback (todo section 10)');
  if (!(await confirm('Turn AeroSpace off and restore previous macOS defaults?'))) return log('Cancelled.');
  if (has('aerospace')) run('aerospace', ['enable', 'off'], { allowFail: true });
  await cmdDefaults('rollback');
  if (flags.uninstall) {
    if (!(await confirm('Also uninstall AeroSpace and delete ~/.aerospace.toml?'))) return log('Kept AeroSpace and its config.');
    run('brew', ['uninstall', '--cask', 'aerospace'], { allowFail: true });
    if (existsSync(AERO_CONFIG)) {
      const backup = `${AERO_CONFIG}.removed-${Date.now()}`;
      if (dryRun) log(c.dim(`[dry-run] mv ${AERO_CONFIG} ${backup}`));
      else {
        copyFileSync(AERO_CONFIG, backup);
        run('rm', [AERO_CONFIG]);
        ok(`config moved aside as ${backup}`);
      }
    }
  } else log('AeroSpace stays installed (windows are back to normal). Add --uninstall to remove it.');
  log('BetterDisplay (if you did phase 4): turn mirroring off, delete the virtual screen, brew uninstall --cask betterdisplay');
}

// ---------------------------------------------------------------- all-in-one

async function cmdSetup() {
  info('Setup: preflight -> defaults -> install -> config -> verify');
  const problems = cmdDoctor();
  if (problems && !(await confirm('Preflight has issues. Continue anyway?'))) return log('Stopped.');
  await cmdDefaults('apply');
  await cmdInstall('aerospace');
  await cmdConfig();
  log();
  log(c.bold('Manual steps left:'));
  log('  1. Accessibility permission for AeroSpace (System Settings -> Privacy & Security).');
  log('  2. node worklab.mjs apps, then re-run config with --route <id>=comms etc.');
  log('  3. Open projects: node worklab.mjs ws 1 ~/path/to/worktree   then   layout 3pane');
  log('  4. Agents: node worklab.mjs grid ~/path/to/project');
}

// ---------------------------------------------------------------- help

function cmdHelp() {
  log(`worklab.mjs - pro workspace setup (AeroSpace + agents grid) for macOS

usage: node worklab.mjs <command> [args] [options]

commands
  doctor                       preflight: disk >= 20% free, swap, heavy processes, conflicting window managers
  setup                        doctor -> defaults -> install -> config -> verify (asks before each change)
  defaults [apply|rollback]    Dock / WindowManager defaults; first run snapshots the originals for exact rollback
  install [aerospace|betterdisplay]
  apps                         list running app ids (for --route / --float)
  config                       generate ~/.aerospace.toml (backs up the old one, reloads AeroSpace)
  profiles                     list config profiles (config --profile intl,comms,tight ...)
  preset list|show|apply <name> [paths...]   launch and tile a whole setup (solo, dev, focus, pair, dual, triple, agents, full, home)
                               own presets: ~/.worklab/presets.json; --wait <s> for how long to wait for windows
  ws <workspace> <path>        launch IDE + terminal dev server + per-workspace browser profile
  grid [dir]                   tmux 2x2 agents session in the 'agents' workspace
  layout <3pane|2x2|pair|accordion|tiles|flatten|balance>   rebuild the layout of the focused workspace
  verify                       section 9 checks
  rollback [--uninstall]       AeroSpace off + restore defaults (+ optionally uninstall)

workspaces: ${WORKSPACES.map((w) => `${w.key}=${w.name}`).join('  ')}

options
  -n, --dry-run                print every change, do nothing
  -y, --yes                    skip confirmations
  config:    --modifier alt|ctrl-alt|cmd-ctrl  (default alt; use ctrl-alt to keep Option+letter typing)
             --gap <px> (default 6)   --float <app-id> (repeat)   --route <app-id>=<workspace> (repeat)
             --print (show the generated toml, write nothing)
  defaults:  --no-animations-tweak    skip the cosmetic animation keys
  ws:        --ide Cursor --term Ghostty|iTerm|Terminal --cmd "npm run dev" --port 3000
             a project with scripts/ux/dev-stack.sh (os-lab) or agents-app/scripts/dev-stack.sh (qLar) starts that stack and opens its port;
             --no-stack uses npm run dev instead
             --browser "Google Chrome"  --no-ide  --no-browser     (env: DEV_IDE, TERM_APP)
  grid:      --agents "claude,codex,aider,ollama run codellama"  (empty = plain shell; default claude,codex,,)
             --session agents  --term ...

examples
  node worklab.mjs doctor
  node worklab.mjs setup --dry-run
  node worklab.mjs config --modifier ctrl-alt --route com.tinyspeck.slackmacgap=comms
  node worklab.mjs ws 1 ~/dev/os-lab --cmd "npm run dev" --port 3000 && node worklab.mjs layout 3pane
  node worklab.mjs grid ~/dev/os-lab --agents "claude,codex,,"
`);
}

// ---------------------------------------------------------------- main

async function main() {
  let parsed;
  try {
    parsed = parseArgs({ args: process.argv.slice(2), options: OPTIONS, allowPositionals: true });
  } catch (e) {
    throw new UserError(`${e.message.replace(/\.$/, '')}. Try: node worklab.mjs help`);
  }
  flags = parsed.values;
  dryRun = Boolean(flags['dry-run']);
  const [cmd = 'help', ...rest] = parsed.positionals;
  if (dryRun) log(c.yellow('DRY RUN: nothing will be changed.'));

  if (flags.help || cmd === 'help') return cmdHelp();
  switch (cmd) {
    case 'doctor': return void cmdDoctor();
    case 'setup': return cmdSetup();
    case 'defaults': return cmdDefaults(rest[0]);
    case 'install': return cmdInstall(rest[0]);
    case 'apps': return cmdApps();
    case 'config': return cmdConfig();
    case 'profiles': return cmdProfiles();
    case 'preset': return cmdPreset(rest[0], rest[1], ...rest.slice(2));
    case 'presets': return cmdPreset('list');
    case 'ws': return cmdWs(rest[0], rest[1]);
    case 'grid': return cmdGrid(rest[0]);
    case 'layout': return cmdLayout(rest[0]);
    case 'verify': return cmdVerify();
    case 'rollback': return cmdRollback();
    default: throw new UserError(`unknown command "${cmd}". Try: node worklab.mjs help`);
  }
}

main().catch((e) => {
  if (e instanceof UserError) {
    console.error(c.red(`error: ${e.message}`));
    process.exit(1);
  }
  throw e;
});
