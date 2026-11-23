// Run: node --test test/
// Runs worklab.mjs against stub binaries and a throwaway HOME. Never touches the real system.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(here, '..', 'worklab.mjs');
const STUB = join(here, 'stub.mjs');
const STUBBED = ['aerospace', 'defaults', 'killall', 'open', 'osascript', 'tmux', 'brew', 'rm'];

let root, home, stubs, logFile, project;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'worklab-test-'));
  home = join(root, 'home');
  stubs = join(root, 'stubs');
  project = join(root, 'project');
  logFile = join(root, 'calls.log');
  for (const d of [home, stubs, project]) mkdirSync(d, { recursive: true });
  writeFileSync(logFile, '');
  for (const name of STUBBED) {
    const f = join(stubs, name);
    writeFileSync(f, `#!/bin/sh\nexec "${process.execPath}" "${STUB}" ${name} "$@"\n`);
    chmodSync(f, 0o755);
  }
});

function wl(args, { env = {}, stdin = '' } = {}) {
  const r = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: 'utf8',
    input: stdin,
    env: {
      PATH: `${stubs}:/usr/bin:/bin:/usr/sbin:/sbin`,
      HOME: home,
      STUB_DIR: stubs,
      STUB_LOG: logFile,
      WORKLAB_NO_SLEEP: '1',
      NO_COLOR: '1',
      ...env,
    },
  });
  const out = (r.stdout + r.stderr).replace(/\x1b\[[0-9;]*m/g, '');
  return { code: r.status, out };
}

const calls = () => readFileSync(logFile, 'utf8').split('\n').filter(Boolean);
const called = (prefix) => calls().some((l) => l.startsWith(prefix));
const seed = (obj) => writeFileSync(join(stubs, 'defaults.json'), JSON.stringify(obj));
const db = () => JSON.parse(readFileSync(join(stubs, 'defaults.json'), 'utf8'));

// ------------------------------------------------------------ basics

test('help lists every command', () => {
  const { code, out } = wl(['help']);
  assert.equal(code, 0);
  for (const cmd of ['doctor', 'setup', 'defaults', 'install', 'apps', 'config', 'profiles', 'preset', 'ws', 'grid', 'layout', 'verify', 'rollback']) {
    assert.match(out, new RegExp(`\\n  ${cmd}\\b`), `help mentions ${cmd}`);
  }
});

test('no args shows help; unknown command and bad flag fail with a message', () => {
  assert.equal(wl([]).code, 0);
  const bad = wl(['nope']);
  assert.equal(bad.code, 1);
  assert.match(bad.out, /unknown command "nope"/);
  const flag = wl(['doctor', '--bogus']);
  assert.equal(flag.code, 1);
  assert.match(flag.out, /bogus/);
});

test('doctor runs and prints a summary', () => {
  const { code, out } = wl(['doctor']);
  assert.equal(code, 0);
  assert.match(out, /Preflight/);
  assert.match(out, /disk free/);
});

// ------------------------------------------------------------ config

test('config --print: bindings, workspaces and floating rules', () => {
  const { code, out } = wl(['config', '--print']);
  assert.equal(code, 0);
  for (const ws of ['0-home', '1-proj-a', '2-proj-b', '3-proj-c', 'agents', 'comms']) {
    assert.match(out, new RegExp(`alt-.* = 'workspace ${ws}'`));
    assert.match(out, new RegExp(`alt-shift-.* = 'move-node-to-workspace ${ws}'`));
  }
  assert.match(out, /alt-shift-right = 'join-with right'/);
  assert.match(out, /esc = \['reload-config', 'mode main'\]/);
  assert.match(out, /pro\.betterdisplay\.BetterDisplay/);
  assert.doesNotMatch(out, /me\.guingrich/);
  assert.doesNotMatch(out, /split (vertical|horizontal)/, 'no split bindings');
  assert.doesNotMatch(out, /\nreload-config =/, 'no invalid service-mode key');
});

test('config --print has no duplicate keys inside any binding table', () => {
  const { out } = wl(['config', '--print']);
  let table = null;
  const seen = new Map();
  for (const line of out.split('\n')) {
    const t = line.match(/^\[(.+)\]$/);
    if (t) {
      table = t[1];
      seen.set(table, new Set());
      continue;
    }
    const kv = line.match(/^([\w-]+) = /);
    if (kv && table?.includes('binding')) {
      assert.ok(!seen.get(table).has(kv[1]), `duplicate ${kv[1]} in [${table}]`);
      seen.get(table).add(kv[1]);
    }
  }
  assert.ok(seen.get('mode.main.binding').size > 30);
});

test('config modifiers, gap, float and route options', () => {
  const { out } = wl(['config', '--print', '--modifier', 'cmd-ctrl', '--gap', '2', '--float', 'com.x.y', '--route', 'com.slack=comms']);
  assert.match(out, /cmd-ctrl-h = 'focus left'/);
  assert.match(out, /inner\.horizontal = 2/);
  assert.match(out, /if\.app-id = 'com\.x\.y'/);
  assert.match(out, /if\.app-id = 'com\.slack'\nrun = 'move-node-to-workspace comms'/);
});

test('config rejects bad input', () => {
  assert.match(wl(['config', '--print', '--modifier', 'hyper']).out, /--modifier must be/);
  assert.match(wl(['config', '--print', '--gap=-1']).out, /--gap must be/);
  assert.match(wl(['config', '--print', '--gap', '-1']).out, /ambiguous/, 'parser rejects a bare negative value');
  assert.match(wl(['config', '--print', '--gap', 'abc']).out, /--gap must be/);
  assert.match(wl(['config', '--print', '--route', 'nope']).out, /app-id=workspace/);
  assert.match(wl(['config', '--print', '--route', 'a=bogus']).out, /not one of/);
  assert.match(wl(['config', '--print', '--profile', 'wat']).out, /unknown profile/);
});

test('profiles combine; flags override them', () => {
  const both = wl(['config', '--print', '--profile', 'intl,tight,comms']).out;
  assert.match(both, /ctrl-alt-1 = 'workspace 1-proj-a'/);
  assert.match(both, /inner\.horizontal = 2/);
  assert.match(both, /com\.anthropic\.claudefordesktop/);
  assert.match(both, /com\.puremac\.app/);
  const over = wl(['config', '--print', '--profile', 'intl,tight', '--modifier', 'alt', '--gap', '9']).out;
  assert.match(over, /alt-1 = 'workspace/);
  assert.match(over, /inner\.horizontal = 9/);
  const list = wl(['profiles']);
  assert.equal(list.code, 0);
  for (const p of ['default', 'intl', 'tight', 'roomy', 'comms']) assert.match(list.out, new RegExp(p));
});

test('config writes, is idempotent, backs up on change and reloads AeroSpace', () => {
  const file = join(home, '.aerospace.toml');
  assert.equal(wl(['config', '--yes']).code, 0);
  assert.ok(existsSync(file));
  assert.ok(called('aerospace reload-config'));
  const first = readFileSync(file, 'utf8');

  const again = wl(['config', '--yes']);
  assert.match(again.out, /already up to date/);

  const changed = wl(['config', '--yes', '--gap', '3']);
  assert.equal(changed.code, 0);
  assert.notEqual(readFileSync(file, 'utf8'), first);
  const backups = readdirSync(home).filter((f) => f.startsWith('.aerospace.toml.bak-'));
  assert.equal(backups.length, 1);
  assert.equal(readFileSync(join(home, backups[0]), 'utf8'), first);
});

test('config without --yes and no TTY refuses to overwrite', () => {
  writeFileSync(join(home, '.aerospace.toml'), '# mine\n');
  const r = wl(['config']);
  assert.equal(r.code, 1);
  assert.match(r.out, /needs confirmation/);
  assert.equal(readFileSync(join(home, '.aerospace.toml'), 'utf8'), '# mine\n');
});

test('config --dry-run writes nothing', () => {
  const r = wl(['config', '--dry-run']);
  assert.equal(r.code, 0);
  assert.ok(!existsSync(join(home, '.aerospace.toml')));
  assert.ok(!called('aerospace reload-config'));
});

// ------------------------------------------------------------ defaults

test('defaults apply: snapshot, writes, Dock restart; snapshot is never overwritten', () => {
  seed({ 'com.apple.dock orientation': 'left', 'com.apple.dock tilesize': '127', 'com.apple.dock mru-spaces': '1' });
  assert.equal(wl(['defaults', 'apply', '--yes']).code, 0);
  const snap = JSON.parse(readFileSync(join(home, '.worklab', 'defaults-snapshot.json'), 'utf8'));
  assert.equal(snap.find((s) => s.key === 'orientation').previous, 'left');
  assert.equal(snap.find((s) => s.key === 'EnableStandardClickToShowDesktop').previous, null);
  assert.ok(called('defaults write com.apple.dock autohide -bool true'));
  assert.ok(called('defaults write com.apple.dock tilesize -int 48'));
  assert.ok(called('killall Dock'));
  assert.equal(db()['com.apple.dock orientation'], 'bottom');

  wl(['defaults', 'apply', '--yes']);
  const snap2 = JSON.parse(readFileSync(join(home, '.worklab', 'defaults-snapshot.json'), 'utf8'));
  assert.equal(snap2.find((s) => s.key === 'orientation').previous, 'left', 'second run keeps the original snapshot');
});

test('defaults apply --no-animations-tweak skips the cosmetic keys', () => {
  wl(['defaults', 'apply', '--yes', '--no-animations-tweak']);
  assert.ok(!called('defaults write NSGlobalDomain'));
  assert.ok(called('defaults write com.apple.dock'));
});

test('defaults rollback restores exact originals and deletes keys that were unset', () => {
  seed({
    'com.apple.dock orientation': 'left',
    'com.apple.dock tilesize': '127',
    'com.apple.dock mru-spaces': '1',
    'com.apple.dock autohide': '0',
    'NSGlobalDomain NSWindowResizeTime': '0.08',
  });
  wl(['defaults', 'apply', '--yes']);
  assert.equal(db()['com.apple.dock orientation'], 'bottom');
  assert.equal(wl(['defaults', 'rollback', '--yes']).code, 0);
  const d = db();
  assert.equal(d['com.apple.dock orientation'], 'left');
  assert.equal(d['com.apple.dock tilesize'], '127');
  assert.equal(d['com.apple.dock mru-spaces'], '1', 'bool 1 restored as true');
  assert.equal(d['com.apple.dock autohide'], '0', 'bool 0 restored as false');
  assert.equal(d['NSGlobalDomain NSWindowResizeTime'], '0.08');
  assert.ok(!('com.apple.WindowManager EnableStandardClickToShowDesktop' in d), 'previously unset key deleted');
  assert.ok(!('NSGlobalDomain NSAutomaticWindowAnimationsEnabled' in d));
});

test('defaults rollback without a snapshot falls back to the todo values', () => {
  wl(['defaults', 'rollback', '--yes']);
  assert.ok(called('defaults write com.apple.dock orientation -string left'));
  assert.ok(called('defaults write com.apple.dock tilesize -int 127'));
  assert.ok(called('defaults delete NSGlobalDomain NSWindowResizeTime'));
});

test('defaults --dry-run and unknown subcommand', () => {
  assert.equal(wl(['defaults', '--dry-run']).code, 0);
  assert.ok(!called('defaults write'));
  assert.ok(!existsSync(join(home, '.worklab')));
  assert.match(wl(['defaults', 'wat']).out, /unknown subcommand/);
});

test('defaults apply without --yes and no TTY refuses', () => {
  const r = wl(['defaults', 'apply']);
  assert.equal(r.code, 1);
  assert.match(r.out, /needs confirmation/);
  assert.ok(!called('defaults write'));
});

// ------------------------------------------------------------ install / apps / verify

test('install aerospace and betterdisplay', () => {
  assert.equal(wl(['install', 'aerospace', '--yes']).code, 0);
  assert.ok(called('open -a AeroSpace'));
  assert.equal(wl(['install', 'betterdisplay', '--yes']).code, 0);
  assert.ok(called('brew install --cask betterdisplay'));
  assert.match(wl(['install', 'wat']).out, /unknown target/);
});

test('apps and verify use aerospace', () => {
  assert.match(wl(['apps']).out, /com\.example\.app/);
  const v = wl(['verify']);
  assert.equal(v.code, 0);
  assert.match(v.out, /1-proj-a/);
});

// ------------------------------------------------------------ layouts

const aeroCalls = () => calls().filter((l) => l.startsWith('aerospace ')).map((l) => l.slice(10)).filter((x) => !x.startsWith('list-'));

test('layout 3pane: flatten, go far left, step right, join right', () => {
  assert.equal(wl(['layout', '3pane']).code, 0);
  const a = aeroCalls();
  assert.deepEqual(a.slice(0, 2), ['flatten-workspace-tree', 'layout tiles horizontal']);
  const joinIdx = a.indexOf('join-with right');
  assert.ok(joinIdx > 0);
  assert.equal(a[joinIdx - 1], 'focus right');
  assert.equal(a.slice(2, joinIdx - 1).filter((x) => x === 'focus left').length, 6);
  assert.equal(a.at(-1), 'balance-sizes');
});

test('layout 3pane/2x2 refuse to touch a workspace with the wrong number of windows', () => {
  const r = wl(['layout', '3pane'], { env: { STUB_WINCOUNT: '13', STUB_FOCUSED: '0-home' } });
  assert.equal(r.code, 1);
  assert.match(r.out, /needs exactly 3 windows, but the focused workspace "0-home" has 13\. Nothing changed/);
  assert.equal(aeroCalls().length, 0, 'no aerospace change was made');
  const r2 = wl(['layout', '2x2'], { env: { STUB_WINCOUNT: '3' } });
  assert.match(r2.out, /needs exactly 4 windows/);
  assert.ok(!aeroCalls().includes('join-with left'));
});

test('layout --force overrides the guard; --workspace switches first; simple layouts have no guard', () => {
  const f = wl(['layout', '3pane', '--force'], { env: { STUB_WINCOUNT: '13' } });
  assert.equal(f.code, 0);
  assert.ok(aeroCalls().includes('join-with right'));
  writeFileSync(logFile, '');
  wl(['layout', '3pane', '--workspace', 'a']);
  assert.equal(aeroCalls()[0], 'workspace agents', 'switches before measuring');
  writeFileSync(logFile, '');
  assert.equal(wl(['layout', 'pair'], { env: { STUB_WINCOUNT: '13' } }).code, 0);
  assert.match(wl(['layout', 'pair', '--workspace', 'nope']).out, /unknown workspace/);
});

test('layout names the workspace it acts on', () => {
  assert.match(wl(['layout', 'pair'], { env: { STUB_FOCUSED: '2-proj-b' } }).out, /layout pair on workspace "2-proj-b"/);
});

test('preset skips (does not abort) a layout whose window count is wrong', () => {
  const r = wl(['preset', 'apply', 'solo', project, '--wait', '0'], { env: { STUB_WINCOUNT: '5' } });
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /layout skipped\. layout 3pane needs exactly 3/);
  assert.ok(!aeroCalls().includes('join-with right'));
  assert.equal(aeroCalls().at(-1), 'workspace 1-proj-a');
});

test('layout 2x2: joins window 2 left, then window 4 left', () => {
  wl(['layout', '2x2'], { env: { STUB_WINCOUNT: '4' } });
  const a = aeroCalls();
  const tail = a.slice(a.indexOf('focus right'));
  assert.deepEqual(tail, ['focus right', 'join-with left', 'focus right', 'focus right', 'join-with left', 'balance-sizes']);
});

test('layout simple modes and bad name', () => {
  for (const [name, expect] of [
    ['accordion', 'layout accordion horizontal vertical'],
    ['tiles', 'layout tiles horizontal vertical'],
    ['flatten', 'flatten-workspace-tree'],
    ['balance', 'balance-sizes'],
  ]) {
    writeFileSync(logFile, '');
    assert.equal(wl(['layout', name]).code, 0);
    assert.ok(aeroCalls().includes(expect), `${name} -> ${expect}`);
  }
  writeFileSync(logFile, '');
  wl(['layout', 'pair']);
  assert.ok(aeroCalls().includes('balance-sizes'));
  assert.match(wl(['layout', 'wat']).out, /layout: use/);
});

test('layout --dry-run only prints', () => {
  const r = wl(['layout', '3pane', '--dry-run']);
  assert.match(r.out, /\[dry-run\] aerospace join-with right/);
  assert.ok(!called('aerospace join-with'));
});

// ------------------------------------------------------------ ws

test('ws launches IDE, terminal and a per-workspace browser profile', () => {
  const r = wl(['ws', '1', project, '--ide', 'Cursor', '--term', 'iTerm', '--cmd', 'echo hi', '--port', '4000']);
  assert.equal(r.code, 0, r.out);
  const c = calls();
  assert.ok(c.includes('aerospace workspace 1-proj-a'));
  assert.ok(c.includes(`open -a Cursor ${project}`));
  assert.ok(c.some((l) => l.startsWith('osascript') && l.includes('iTerm') && l.includes('echo hi')));
  assert.ok(c.some((l) => l.startsWith('open -na Google Chrome') && l.includes('localhost:4000') && l.includes('.chrome-dev/1-proj-a')));
  assert.ok(existsSync(join(home, '.chrome-dev', '1-proj-a')));
  assert.ok(c.indexOf(`open -a Cursor ${project}`) < c.findIndex((l) => l.startsWith('osascript')), 'IDE opens before terminal');
});

test('ws moves every newly opened window to the target workspace by id', () => {
  const r = wl(['ws', '3', project, '--ide', 'Cursor', '--term', 'iTerm']);
  assert.equal(r.code, 0, r.out);
  const moves = aeroCalls().filter((x) => x.startsWith('move-node-to-workspace'));
  assert.deepEqual(moves, [
    'move-node-to-workspace --window-id 101 3-proj-c', // IDE
    'move-node-to-workspace --window-id 102 3-proj-c', // terminal
    'move-node-to-workspace --window-id 103 3-proj-c', // browser
  ]);
  assert.equal(aeroCalls().at(-1), 'workspace 3-proj-c', 'ends on the target workspace');
});

test('ws warns instead of moving random windows when nothing new appears', () => {
  const r = wl(['ws', '1', project, '--no-browser', '--term', 'Terminal', '--claim-wait', '0'], { env: { STUB_NO_WINDOWS: '1' } });
  assert.equal(r.code, 0);
  assert.match(r.out, /ide: no new window appeared/);
  assert.match(r.out, /terminal: no new window appeared/);
  assert.ok(!aeroCalls().some((x) => x.startsWith('move-node-to-workspace')));
});

test('iTerm gets a new window and the command is typed into it (not passed as a quoted command)', () => {
  wl(['ws', '1', project, '--term', 'iTerm', '--no-ide', '--no-browser', '--cmd', 'echo hi']);
  const line = calls().find((l) => l.startsWith('osascript'));
  assert.match(line, /create window with default profile\)/);
  assert.match(line, /write text/);
  assert.doesNotMatch(line, /zsh -c/);
});

test('grid moves its terminal window to the agents workspace', () => {
  wl(['grid', project, '--term', 'Ghostty']);
  assert.ok(aeroCalls().some((x) => /^move-node-to-workspace --window-id \d+ agents$/.test(x)));
});

test('ws terminals: Ghostty and Terminal', () => {
  wl(['ws', 'agents', project, '--term', 'Ghostty', '--no-ide', '--no-browser']);
  assert.ok(calls().some((l) => l.startsWith('open -na Ghostty --args --working-directory=') && l.includes('exec zsh')));
  writeFileSync(logFile, '');
  wl(['ws', 'comms', project, '--term', 'Terminal', '--no-ide', '--no-browser']);
  assert.ok(calls().some((l) => l.startsWith('osascript') && l.includes('Terminal')));
});

test('ws --no-ide --no-browser opens only the terminal', () => {
  wl(['ws', '2-proj-b', project, '--term', 'Terminal', '--no-ide', '--no-browser']);
  assert.ok(!called('open -a'));
  assert.ok(!called('open -na Google'));
});

test('ws input validation', () => {
  assert.match(wl(['ws']).out, /usage: worklab ws/);
  assert.match(wl(['ws', 'zzz', project]).out, /unknown workspace/);
  assert.match(wl(['ws', '1', join(root, 'missing')]).out, /path not found/);
  assert.match(wl(['ws', '1', project, '--port', 'abc']).out, /--port must be a number/);
  assert.match(wl(['ws', '1', project, '--term', 'Nope', '--no-ide', '--no-browser']).out, /Unknown terminal/);
});

test('ws shell quoting: a path with a quote cannot break out of the command', () => {
  const evil = join(root, "it's $(touch pwned)");
  mkdirSync(evil);
  wl(['ws', '1', evil, '--term', 'Terminal', '--no-ide', '--no-browser']);
  const line = calls().find((l) => l.startsWith('osascript'));
  assert.ok(line.includes("'\\\\''") || line.includes("'\\''"), 'single quote is escaped');
  assert.ok(!existsSync(join(root, 'pwned')));
});

// ------------------------------------------------------------ grid

test('grid builds the tmux 2x2 and sends agent commands', () => {
  const r = wl(['grid', project, '--term', 'Ghostty']);
  assert.equal(r.code, 0, r.out);
  const t = calls().filter((l) => l.startsWith('tmux ')).map((l) => l.slice(5));
  assert.equal(t[0], 'kill-session -t agents');
  assert.ok(t[1].startsWith('new-session -d -s agents'));
  assert.equal(t.filter((x) => x.startsWith('split-window')).length, 3);
  assert.ok(t.includes('select-layout -t agents:0 tiled'));
  assert.ok(t.includes('send-keys -t agents:0.0 claude C-m'));
  assert.ok(t.includes('send-keys -t agents:0.1 codex C-m'));
  assert.ok(!t.some((x) => x.startsWith('send-keys -t agents:0.2')), 'empty entry = plain shell');
  assert.ok(called('aerospace workspace agents'));
  assert.ok(called('open -na Ghostty --args -e tmux attach -t agents'));
});

test('grid --agents, --session, and limits', () => {
  wl(['grid', project, '--agents', 'echo a,echo b,echo c,echo d', '--session', 'lab', '--term', 'Ghostty']);
  const t = calls();
  assert.ok(t.includes('tmux send-keys -t lab:0.3 echo d C-m'));
  assert.match(wl(['grid', project, '--agents', 'a,b,c,d,e']).out, /at most 4/);
  assert.match(wl(['grid', join(root, 'nope')]).out, /path not found/);
});

test('grid with iTerm attaches through osascript', () => {
  wl(['grid', project, '--term', 'iTerm']);
  assert.ok(calls().some((l) => l.startsWith('osascript') && l.includes('tmux attach -t agents')));
});

// ------------------------------------------------------------ presets

test('preset list and show cover every built-in', () => {
  const list = wl(['preset', 'list']);
  for (const n of ['home', 'solo', 'focus', 'pair', 'dual', 'triple', 'agents', 'full']) assert.match(list.out, new RegExp(`\\n  ${n}\\b`));
  assert.equal(wl(['presets']).code, 0);
  assert.match(wl(['preset', 'show', 'dual']).out, /"2-proj-b"/);
  assert.match(wl(['preset', 'show', 'nope']).out, /unknown preset/);
  assert.match(wl(['preset', 'bogus']).out, /preset: use/);
});

test('preset solo: launch all three, 3pane, focus', () => {
  const r = wl(['preset', 'apply', 'solo', project, '--term', 'iTerm', '--ide', 'Cursor']);
  assert.equal(r.code, 0, r.out);
  const a = aeroCalls();
  assert.ok(a.includes('workspace 1-proj-a'));
  assert.ok(a.includes('join-with right'));
  assert.ok(called(`open -a Cursor ${project}`));
  assert.equal(a[a.length - 1], 'workspace 1-proj-a', 'ends focused on the project workspace');
});

test('preset focus, pair, home', () => {
  wl(['preset', 'apply', 'focus', project]);
  assert.ok(aeroCalls().includes('layout accordion horizontal vertical'));
  assert.ok(!called('open -na Google'));
  writeFileSync(logFile, '');
  wl(['preset', 'apply', 'pair', project]);
  assert.ok(called('open -na Google Chrome'));
  assert.ok(!calls().some((l) => l.startsWith('osascript')), 'pair has no terminal');
  writeFileSync(logFile, '');
  wl(['preset', 'apply', 'home']);
  assert.deepEqual(aeroCalls(), ['workspace 0-home']);
});

test('preset dual and triple use one path per project', () => {
  const p2 = join(root, 'p2');
  const p3 = join(root, 'p3');
  mkdirSync(p2);
  mkdirSync(p3);
  wl(['preset', 'apply', 'dual', project, p2, '--term', 'Terminal', '--ide', 'Cursor']);
  assert.ok(called(`open -a Cursor ${project}`));
  assert.ok(called(`open -a Cursor ${p2}`));
  assert.ok(aeroCalls().includes('workspace 2-proj-b'));
  assert.match(wl(['preset', 'apply', 'dual', project]).out, /needs 2 project path/);
  writeFileSync(logFile, '');
  wl(['preset', 'apply', 'triple', project, p2, p3, '--term', 'Terminal']);
  assert.ok(aeroCalls().includes('workspace 3-proj-c'));
  assert.match(wl(['preset', 'apply', 'triple', project, p2]).out, /needs 3 project path/);
});

test('preset agents and full build the tmux grid', () => {
  wl(['preset', 'apply', 'agents', '--term', 'Ghostty']);
  assert.ok(called('tmux new-session -d -s agents'));
  assert.equal(aeroCalls().at(-1), 'workspace agents');
  writeFileSync(logFile, '');
  wl(['preset', 'apply', 'full', project, '--term', 'Ghostty']);
  assert.ok(called('tmux new-session -d -s agents'));
  assert.ok(aeroCalls().includes('join-with right'));
  assert.equal(aeroCalls().at(-1), 'workspace 1-proj-a');
});

test('preset warns and skips 3pane when windows are missing', () => {
  const r = wl(['preset', 'apply', 'solo', project, '--wait', '0'], { env: { STUB_WINCOUNT: '1' } });
  assert.equal(r.code, 0);
  assert.match(r.out, /1 of 3 windows appeared/);
  assert.match(r.out, /skipping 3pane/);
  assert.ok(!aeroCalls().includes('join-with right'));
});

test('preset --dry-run launches nothing', () => {
  const r = wl(['preset', 'apply', 'solo', project, '--dry-run']);
  assert.equal(r.code, 0);
  assert.equal(calls().filter((l) => !l.startsWith('defaults') && !l.startsWith('aerospace list-')).length, 0, 'only read-only queries ran');
  assert.match(r.out, /\[dry-run\] aerospace join-with right/);
});

test('dev preset: a project with a dev-stack script starts it and opens its port', () => {
  mkdirSync(join(project, 'agents-app', 'scripts'), { recursive: true });
  writeFileSync(join(project, 'agents-app', 'scripts', 'dev-stack.sh'), '#!/bin/sh\n');
  const r = wl(['preset', 'apply', 'dev', project, '--term', 'Terminal', '--wait', '0', '--dry-run']);
  assert.equal(r.code, 0);
  assert.match(r.out, /dev stack found: .*agents-app\/scripts\/dev-stack\.sh \(browser on :8140/);
  assert.match(r.out, /dev-stack\.sh' start; .*dev-stack\.sh' status/);
  assert.match(r.out, /localhost:8140/);
});

test('--no-stack and projects without a stack keep npm run dev on port 3000', () => {
  mkdirSync(join(project, 'agents-app', 'scripts'), { recursive: true });
  writeFileSync(join(project, 'agents-app', 'scripts', 'dev-stack.sh'), '#!/bin/sh\n');
  const off = wl(['preset', 'apply', 'solo', project, '--term', 'Terminal', '--no-stack', '--dry-run']);
  assert.doesNotMatch(off.out, /dev stack found/);
  assert.match(off.out, /npm run dev/);
  assert.match(off.out, /localhost:3000/);
});

test('user presets from ~/.worklab/presets.json are loaded and validated', () => {
  mkdirSync(join(home, '.worklab'), { recursive: true });
  const f = join(home, '.worklab', 'presets.json');
  writeFileSync(f, JSON.stringify({ mine: { desc: 'my setup', projects: 1, workspaces: [{ ws: '2', project: 0, parts: ['term'], layout: 'tiles' }], focus: '2-proj-b' } }));
  assert.match(wl(['preset', 'list']).out, /\n  mine\b.*my setup/);
  assert.equal(wl(['preset', 'apply', 'mine', project, '--term', 'Terminal']).code, 0);
  assert.ok(aeroCalls().includes('workspace 2-proj-b'));
  assert.ok(aeroCalls().includes('layout tiles horizontal vertical'));

  writeFileSync(f, JSON.stringify({ bad: { workspaces: [{ ws: '1', layout: 'spiral' }] } }));
  assert.match(wl(['preset', 'list']).out, /unknown layout "spiral"/);
  writeFileSync(f, JSON.stringify({ bad: { workspaces: [{ ws: 'nope' }] } }));
  assert.match(wl(['preset', 'list']).out, /unknown workspace/);
  writeFileSync(f, JSON.stringify({ bad: { workspaces: [{ ws: '1', parts: ['printer'] }] } }));
  assert.match(wl(['preset', 'list']).out, /unknown part "printer"/);
  writeFileSync(f, '{nope');
  assert.match(wl(['preset', 'list']).out, /not valid JSON/);
});

// ------------------------------------------------------------ rollback / setup

test('rollback: AeroSpace off + defaults restored; AeroSpace kept without --uninstall', () => {
  seed({ 'com.apple.dock orientation': 'left' });
  wl(['defaults', 'apply', '--yes']);
  const r = wl(['rollback', '--yes']);
  assert.equal(r.code, 0, r.out);
  assert.ok(called('aerospace enable off'));
  assert.equal(db()['com.apple.dock orientation'], 'left');
  assert.ok(!called('brew uninstall'));
  assert.match(r.out, /stays installed/);
});

test('rollback --uninstall removes AeroSpace and moves the config aside', () => {
  wl(['config', '--yes']);
  const r = wl(['rollback', '--yes', '--uninstall']);
  assert.equal(r.code, 0, r.out);
  assert.ok(called('brew uninstall --cask aerospace'));
  assert.ok(called(`rm ${join(home, '.aerospace.toml')}`));
  assert.ok(readdirSync(home).some((f) => f.startsWith('.aerospace.toml.removed-')));
});

test('rollback --dry-run changes nothing', () => {
  wl(['rollback', '--dry-run', '--uninstall']);
  assert.equal(calls().length, 0);
});

test('setup --yes runs the whole chain', () => {
  const r = wl(['setup', '--yes']);
  assert.equal(r.code, 0, r.out);
  assert.ok(called('defaults write com.apple.dock'));
  assert.ok(called('open -a AeroSpace'));
  assert.ok(existsSync(join(home, '.aerospace.toml')));
  assert.match(r.out, /Manual steps left/);
});

test('setup --dry-run changes nothing', () => {
  const r = wl(['setup', '--dry-run']);
  assert.equal(r.code, 0);
  assert.ok(!existsSync(join(home, '.aerospace.toml')));
  assert.ok(!existsSync(join(home, '.worklab')));
  assert.ok(!called('defaults write'));
});

test('commands that need aerospace fail clearly when it is missing', () => {
  // empty stub dir without aerospace, PATH has only system dirs
  const f = join(stubs, 'aerospace');
  writeFileSync(f, '#!/bin/sh\nexit 127\n');
  // simulate "not installed" by removing the stub entirely
  spawnSync('rm', [f]);
  for (const args of [['apps'], ['layout', '3pane'], ['grid', project], ['ws', '1', project], ['preset', 'apply', 'home']]) {
    const r = wl(args);
    assert.equal(r.code, 1, args.join(' '));
    assert.match(r.out, /aerospace not found/);
  }
});
