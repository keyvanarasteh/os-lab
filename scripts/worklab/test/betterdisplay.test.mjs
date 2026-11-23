// Run: node --test test/
// Exercises betterdisplay.mjs against a stateful betterdisplaycli stub and a throwaway HOME.
// Never touches the real displays.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BetterDisplayCli, DisplayMode, HealthGuard, Plan, Preset, PresetRegistry, Resolution, Step } from '../betterdisplay.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const SCRIPT = join(here, '..', 'betterdisplay.mjs');
const STUB = join(here, 'bd-stub.mjs');
const STUBBED = ['betterdisplaycli', 'aerospace', 'ps'];

let root, home, stubs, logFile;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'bd-test-'));
  home = join(root, 'home');
  stubs = join(root, 'stubs');
  logFile = join(root, 'calls.log');
  for (const d of [home, stubs]) mkdirSync(d, { recursive: true });
  writeFileSync(logFile, '');
  for (const name of STUBBED) {
    const f = join(stubs, name);
    writeFileSync(f, `#!/bin/sh\nexec "${process.execPath}" "${STUB}" ${name} "$@"\n`);
    chmodSync(f, 0o755);
  }
});

function bd(args, { env = {}, path } = {}) {
  const r = spawnSync(process.execPath, [SCRIPT, ...args], {
    encoding: 'utf8',
    env: {
      PATH: path ?? `${stubs}:/usr/bin:/bin:/usr/sbin:/sbin`,
      HOME: home,
      STUB_DIR: stubs,
      STUB_LOG: logFile,
      WORKLAB_NO_SLEEP: '1',
      WORKLAB_SWAP_MB: '100',
      NO_COLOR: '1',
      ...env,
    },
  });
  return { code: r.status, out: (r.stdout + r.stderr).replace(/\x1b\[[0-9;]*m/g, '') };
}

const calls = () => readFileSync(logFile, 'utf8').split('\n').filter(Boolean);
const cliCalls = () => calls().filter((l) => l.startsWith('betterdisplaycli '));
const writes = () => cliCalls().filter((l) => /^betterdisplaycli (set|create|discard) /.test(l));
const db = () => JSON.parse(readFileSync(join(stubs, 'bd.json'), 'utf8'));
const disp = (name) => db().displays.find((d) => d.name === name);
const stateFile = () => join(home, '.worklab', 'display-state.json');
const clearLog = () => writeFileSync(logFile, '');

// ============================================================ value types

test('Resolution: parse, aspect, ppi and framebuffer estimate', () => {
  const r = Resolution.parse('2560x1440');
  assert.equal(String(r), '2560x1440');
  assert.deepEqual(r.aspect, [16, 9]);
  assert.equal(Math.round(Resolution.parse('1920x1080').ppi(32)), 69);
  assert.equal(Math.round(r.ppi(32)), 92);
  assert.equal(r.framebufferMB(true), 169); // 5120x2880x4 x3 buffers
  assert.equal(r.framebufferMB(false), 42);
  assert.ok(Resolution.parse('2560X1440').equals(r));
  assert.deepEqual(Resolution.parse('2304x1296').aspect, [16, 9]);
  for (const bad of ['2560', 'axb', '10x10', '2560x', '99999x99999', '']) assert.throws(() => Resolution.parse(bad), /resolution|invalid/);
});

test('DisplayMode.parse reads the CLI mode list format', () => {
  const m = DisplayMode.parse('12 - 2560x1440 HiDPI 144Hz 10bpc');
  assert.equal(m.index, 12);
  assert.equal(String(m.resolution), '2560x1440');
  assert.equal(m.hiDPI, true);
  assert.equal(m.hz, 144);
  const plain = DisplayMode.parse('3 - 800x600 60Hz 10bpc');
  assert.equal(plain.hiDPI, false);
  assert.equal(DisplayMode.parse('nonsense'), null);
});

test('BetterDisplayCli.flags builds arguments (true = bare flag, false/undefined skipped)', () => {
  assert.deepEqual(BetterDisplayCli.flags({ name: 'X', identifiers: true, off: false, skip: undefined, n: 0 }), ['--name=X', '--identifiers', '--n=0']);
});

test('Preset validation', () => {
  assert.throws(() => new Preset('x', { kind: 'canvas' }), /need a resolution/);
  assert.throws(() => new Preset('x', { kind: 'weird' }), /unknown kind/);
  assert.throws(() => new Preset('x', { kind: 'light' }), /need a brightness/);
  assert.throws(() => new Preset('x', { kind: 'light', brightness: 0 }), /brightness must be 1-100/);
  assert.throws(() => new Preset('x', { kind: 'light', brightness: 101 }), /brightness must be 1-100/);
  const p = new Preset('x', { kind: 'canvas', resolution: '2560x1440' });
  assert.equal(p.virtualName, 'worklab-2560x1440');
  assert.equal(p.hiDPI, true);
});

test('PresetRegistry: built-ins, combos and conflicts', () => {
  const reg = new PresetRegistry(join(root, 'none.json'));
  assert.deepEqual(reg.list().map((p) => p.name), ['native', 'comfort', 'dev', 'max', 'bright', 'day', 'evening', 'night']);
  const { base, light } = reg.resolve('dev+evening');
  assert.equal(base.name, 'dev');
  assert.equal(light.name, 'evening');
  assert.equal(reg.resolve('night').base, null);
  assert.throws(() => reg.resolve('dev+comfort'), /more than one canvas/);
  assert.throws(() => reg.resolve('day+night'), /more than one brightness/);
  assert.throws(() => reg.resolve('wat'), /unknown preset "wat"/);
  assert.throws(() => reg.resolve(''), /no preset given/);
});

test('Plan.execute undoes completed steps in reverse when a later step fails', () => {
  const order = [];
  const log = { info() {}, warn() {} };
  const plan = new Plan([
    new Step('a', () => order.push('a'), () => order.push('undo a')),
    new Step('b', () => order.push('b'), () => order.push('undo b')),
    new Step('c', () => {
      throw new Error('boom');
    }, () => order.push('undo c')),
  ]);
  assert.throws(() => plan.execute(log), /boom/);
  assert.deepEqual(order, ['a', 'b', 'undo b', 'undo a'], 'failed step itself is not undone');
});

test('HealthGuard honours the limit', () => {
  process.env.WORKLAB_SWAP_MB = '1000';
  assert.equal(new HealthGuard(null).check().ok, true);
  process.env.WORKLAB_SWAP_MB = '3000';
  const bad = new HealthGuard(null).check();
  assert.equal(bad.ok, false);
  assert.match(bad.reason, /3000 MB/);
  delete process.env.WORKLAB_SWAP_MB;
});

// ============================================================ read-only commands

test('help, presets and preset show', () => {
  const h = bd(['help']);
  assert.equal(h.code, 0);
  for (const c of ['status', 'doctor', 'modes', 'preset apply', 'revert', 'resolution', 'refresh', 'brightness', 'mirror', 'virtual', 'raw get']) assert.match(h.out, new RegExp(c));
  assert.equal(bd([]).code, 0);
  const p = bd(['presets']);
  for (const n of ['native', 'comfort', 'dev', 'max', 'bright', 'day', 'evening', 'night']) assert.match(p.out, new RegExp(`\\n  ${n}\\b|^  ${n}\\b`));
  assert.match(p.out, /2560x1440 HiDPI \(~92 PPI at 32", ~169 MB framebuffer\)/);
  const show = JSON.parse(bd(['preset', 'show', 'dev']).out);
  assert.equal(show.resolution, '2560x1440');
  assert.deepEqual(show.logical, ['1920x1080', '2304x1296', '2560x1440']);
  assert.match(bd(['preset', 'show', 'nope']).out, /unknown preset/);
  assert.match(bd(['preset', 'show']).out, /usage: preset show/);
  assert.match(bd(['preset', 'wat']).out, /preset: use/);
  assert.match(bd(['nope']).out, /unknown command/);
  assert.match(bd(['status', '--bogus']).out, /bogus/);
});

test('status lists the panel with live values and swap', () => {
  const r = bd(['status']);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /physical\s+32G1WG4\s+main \| 1920x1080 \| 144Hz \| brightness 100% \| mirror off/);
  assert.match(r.out, /active preset: none/);
  assert.match(r.out, /swap used: 100 MB/);
});

test('doctor: healthy, then each problem', () => {
  const ok = bd(['doctor']);
  assert.equal(ok.code, 0);
  assert.match(ok.out, /single BetterDisplay instance/);
  assert.match(ok.out, /Pro features available/);
  assert.match(ok.out, /Looks good/);

  const twin = bd(['doctor'], { env: { BD_PS: '100 /Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay\n200 /Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay --version' } });
  assert.match(twin.out, /2 BetterDisplay instances running \(100, 200\)/);

  assert.match(bd(['doctor'], { env: { BD_PRO: 'off' } }).out, /Pro features not available/);
  assert.match(bd(['doctor'], { env: { WORKLAB_SWAP_MB: '5000' } }).out, /swap used is 5000 MB/);
  assert.match(bd(['doctor'], { env: { STUB_MONITORS: '2' } }).out, /AeroSpace sees 2 monitors/);
  assert.match(bd(['doctor'], { path: '/usr/bin:/bin' }).out, /betterdisplaycli not found/);
});

test('modes: list, hidpi filter, text filter', () => {
  const all = bd(['modes']).out;
  assert.match(all, /4 mode\(s\) on 32G1WG4/);
  const hi = bd(['modes', '--hidpi', 'on']).out;
  assert.match(hi, /1 mode\(s\)/);
  assert.match(hi, /1920x1080 HiDPI 144Hz/);
  assert.match(bd(['modes', '--filter', '2560']).out, /1 mode\(s\)/);
  assert.match(bd(['modes', '--hidpi', 'maybe']).out, /--hidpi must be on or off/);
  assert.match(bd(['modes', '--display', 'Nope']).out, /no display named "Nope"/);
});

test('raw only passes through well-formed get arguments', () => {
  assert.match(bd(['raw', 'get', '--name=32G1WG4', '--resolution']).out, /1920x1080/);
  assert.match(bd(['raw', 'set', '--name=x']).out, /only passes through `get`/);
  assert.match(bd(['raw', 'get', '--version']).out, /not an accepted argument/);
  assert.match(bd(['raw', 'get', 'version']).out, /not an accepted argument/);
  assert.match(bd(['raw', 'get', '--name=a; rm -rf /']).out, /not an accepted argument/);
});

test('virtual list', () => {
  assert.match(bd(['virtual']).out, /0 virtual screen/);
  assert.match(bd(['virtual', 'create']).out, /virtual: use list/);
});

// ============================================================ presets: apply

test('preset apply dev --dry-run prints the plan and changes nothing', () => {
  const r = bd(['preset', 'apply', 'dev', '--dry-run']);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /\[dry-run\] betterdisplaycli create --type=VirtualScreen --virtualScreenName=worklab-2560x1440/);
  assert.match(r.out, /--resolutionList=1920x1080,2304x1296,2560x1440/);
  assert.match(r.out, /\[dry-run\] betterdisplaycli set --name=32G1WG4 --mirror=on --targetName=worklab-2560x1440/);
  assert.equal(writes().length, 0);
  assert.ok(!existsSync(stateFile()));
});

test('preset apply dev: creates, sizes, mirrors, verifies, snapshots the original', () => {
  const r = bd(['preset', 'apply', 'dev', '--yes']);
  assert.equal(r.code, 0, r.out);
  const w = writes();
  assert.match(w[0], /^betterdisplaycli create --type=VirtualScreen --virtualScreenName=worklab-2560x1440 --aspectWidth=16 --aspectHeight=9 --sizeInch=32 --virtualScreenHiDPI=on --useResolutionList=on --resolutionList=1920x1080,2304x1296,2560x1440$/);
  assert.equal(w[1], 'betterdisplaycli set --name=worklab-2560x1440 --resolution=2560x1440 --hiDPI=on');
  assert.equal(w[2], 'betterdisplaycli set --name=32G1WG4 --mirror=on --targetName=worklab-2560x1440');
  assert.equal(w.length, 3);

  assert.equal(disp('worklab-2560x1440').props.resolution, '2560x1440');
  assert.equal(disp('32G1WG4').props.mirror, 'on');

  const st = JSON.parse(readFileSync(stateFile(), 'utf8'));
  assert.equal(st.resolution, '1920x1080');
  assert.equal(st.refresh, '144Hz');
  assert.equal(st.brightnessPct, 100);
  assert.equal(st.applied, 'dev');
  assert.match(r.out, /Undo with: node betterdisplay\.mjs revert/);
});

test('preset apply uses --size-inch and --mirror-source physical', () => {
  bd(['preset', 'apply', 'comfort', '--yes', '--size-inch', '27', '--mirror-source', 'physical']);
  assert.ok(cliCalls().some((l) => l.includes('--sizeInch=27')));
  assert.ok(cliCalls().includes('betterdisplaycli set --name=worklab-2304x1296 --mirror=on --targetName=32G1WG4'));
  assert.match(bd(['preset', 'apply', 'dev', '--yes', '--mirror-source', 'sideways']).out, /--mirror-source must be/);
  assert.match(bd(['preset', 'apply', 'dev', '--yes', '--size-inch', '1']).out, /--size-inch must be 5-100/);
});

test('swap guard refuses canvas presets unless --force; brightness and native are exempt', () => {
  const env = { WORKLAB_SWAP_MB: '4200' };
  const refused = bd(['preset', 'apply', 'dev', '--yes'], { env });
  assert.equal(refused.code, 1);
  assert.match(refused.out, /swap used is 4200 MB \(limit 2048 MB\)/);
  assert.equal(writes().length, 0);
  assert.ok(!existsSync(stateFile()));

  assert.equal(bd(['preset', 'apply', 'night', '--yes'], { env }).code, 0, 'brightness is exempt');
  assert.equal(bd(['preset', 'apply', 'native', '--yes'], { env }).code, 0, 'native is exempt');
  clearLog();
  assert.equal(bd(['preset', 'apply', 'dev', '--yes', '--force'], { env }).code, 0);
  assert.ok(writes().some((l) => l.includes('create')));
});

test('switching canvas presets removes the old worklab screen and keeps the first snapshot', () => {
  bd(['preset', 'apply', 'dev', '--yes']);
  clearLog();
  const r = bd(['preset', 'apply', 'comfort', '--yes']);
  assert.equal(r.code, 0, r.out);
  const w = writes();
  assert.equal(w[0], 'betterdisplaycli set --name=32G1WG4 --mirror=off');
  assert.equal(w[1], 'betterdisplaycli discard --type=VirtualScreen --name=worklab-2560x1440');
  assert.ok(w[2].startsWith('betterdisplaycli create') && w[2].includes('worklab-2304x1296'));
  assert.deepEqual(db().displays.map((d) => d.name), ['32G1WG4', 'worklab-2304x1296']);
  const st = JSON.parse(readFileSync(stateFile(), 'utf8'));
  assert.equal(st.resolution, '1920x1080', 'original, not the dev canvas');
  assert.equal(st.applied, 'comfort');
});

test('re-applying the same canvas reuses the virtual screen', () => {
  bd(['preset', 'apply', 'dev', '--yes']);
  clearLog();
  bd(['preset', 'apply', 'dev', '--yes']);
  assert.ok(!writes().some((l) => l.startsWith('betterdisplaycli create')), 'no second create');
  assert.equal(db().displays.filter((d) => d.deviceType === 'VirtualScreen').length, 1);
});

test('combined presets: canvas + brightness; invalid combos are refused before any change', () => {
  const r = bd(['preset', 'apply', 'dev+evening', '--yes']);
  assert.equal(r.code, 0, r.out);
  assert.ok(cliCalls().includes('betterdisplaycli set --name=32G1WG4 --brightness=55%'));
  assert.equal(disp('32G1WG4').props.brightness, '0.55');
  clearLog();
  assert.match(bd(['preset', 'apply', 'dev+comfort', '--yes']).out, /more than one canvas/);
  assert.match(bd(['preset', 'apply', 'day+night', '--yes']).out, /more than one brightness/);
  assert.equal(writes().length, 0);
});

test('brightness-only preset', () => {
  assert.equal(bd(['preset', 'apply', 'night', '--yes']).code, 0);
  assert.equal(disp('32G1WG4').props.brightness, '0.3');
  assert.deepEqual(db().displays.map((d) => d.name), ['32G1WG4'], 'no virtual screen created');
});

test('native removes worklab screens only, never other virtual screens', () => {
  bd(['preset', 'apply', 'dev', '--yes']);
  const state = db();
  state.displays.push({ name: 'MyVirtual', deviceType: 'VirtualScreen', tagID: '99', UUID: 'MV', displayID: '99', props: { resolution: '1280x720', mirror: 'off', main: 'false' }, modes: [] });
  writeFileSync(join(stubs, 'bd.json'), JSON.stringify(state));
  clearLog();
  const r = bd(['preset', 'apply', 'native', '--yes']);
  assert.equal(r.code, 0, r.out);
  assert.deepEqual(db().displays.map((d) => d.name), ['32G1WG4', 'MyVirtual']);
  assert.equal(disp('32G1WG4').props.mirror, 'off');
  assert.equal(disp('32G1WG4').props.resolution, '1920x1080');
  assert.ok(!cliCalls().some((l) => l.includes('MyVirtual') && /discard|set/.test(l)));
});

test('discard is never issued without --name (the real CLI would delete every virtual screen)', () => {
  bd(['preset', 'apply', 'dev', '--yes']);
  bd(['preset', 'apply', 'comfort', '--yes']);
  bd(['preset', 'apply', 'native', '--yes']);
  bd(['revert', '--yes']);
  const discards = cliCalls().filter((l) => l.startsWith('betterdisplaycli discard'));
  assert.ok(discards.length >= 3);
  for (const d of discards) assert.match(d, /--name=worklab-\d+x\d+/);
});

test('apply failure after create undoes the created screen and the mirror', () => {
  const r = bd(['preset', 'apply', 'dev', '--yes'], { env: { BD_FAIL: 'mirror' } });
  assert.equal(r.code, 1);
  assert.match(r.out, /undoing completed steps/);
  assert.deepEqual(db().displays.map((d) => d.name), ['32G1WG4'], 'created screen removed');
  assert.equal(disp('32G1WG4').props.mirror ?? 'off', 'off');
  assert.ok(cliCalls().some((l) => l.startsWith('betterdisplaycli discard') && l.includes('worklab-2560x1440')));
});

test('a mirror that did not take effect fails verification and is undone', () => {
  // make `set --mirror=on` a silent no-op by failing only reads of mirror state: simulate with BD_FAIL on resolution? Use a stub-level flag instead.
  const r = bd(['preset', 'apply', 'dev', '--yes'], { env: { BD_FAIL: 'hiDPI' } });
  assert.equal(r.code, 1);
  assert.deepEqual(db().displays.map((d) => d.name), ['32G1WG4']);
});

test('AeroSpace seeing two monitors after a canvas apply produces a warning', () => {
  const r = bd(['preset', 'apply', 'dev', '--yes'], { env: { STUB_MONITORS: '2' } });
  assert.equal(r.code, 0);
  assert.match(r.out, /AeroSpace sees 2 monitors; the virtual screen may be acting as a second monitor/);
});

test('apply asks for confirmation without a TTY', () => {
  const r = bd(['preset', 'apply', 'dev']);
  assert.equal(r.code, 1);
  assert.match(r.out, /needs confirmation/);
  assert.equal(writes().length, 0);
});

// ============================================================ revert

test('revert restores resolution, brightness, refresh; removes the canvas; clears the snapshot', () => {
  bd(['preset', 'apply', 'dev+night', '--yes']);
  assert.equal(disp('32G1WG4').props.brightness, '0.3');
  clearLog();
  const r = bd(['revert', '--yes']);
  assert.equal(r.code, 0, r.out);
  assert.deepEqual(db().displays.map((d) => d.name), ['32G1WG4']);
  const p = disp('32G1WG4').props;
  assert.equal(p.mirror, 'off');
  assert.equal(p.resolution, '1920x1080');
  assert.equal(p.hiDPI, 'off');
  assert.equal(p.brightness, '1');
  assert.equal(p.refreshRate, '144Hz');
  assert.ok(!existsSync(stateFile()));
  assert.match(r.out, /reverted: 32G1WG4 1920x1080/);
});

test('revert without a snapshot falls back to native 1080p', () => {
  const r = bd(['revert', '--yes']);
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /No saved state/);
  assert.ok(cliCalls().includes('betterdisplaycli set --name=32G1WG4 --resolution=1920x1080 --hiDPI=off'));
});

test('revert --dry-run changes nothing and keeps the snapshot', () => {
  bd(['preset', 'apply', 'dev', '--yes']);
  clearLog();
  assert.equal(bd(['revert', '--dry-run']).code, 0);
  assert.equal(writes().length, 0);
  assert.ok(existsSync(stateFile()));
  assert.equal(db().displays.length, 2);
});

// ============================================================ simple controls

test('resolution validates against the mode list unless --force', () => {
  assert.equal(bd(['resolution', '1280x720']).code, 0);
  assert.equal(disp('32G1WG4').props.resolution, '1280x720');
  const bad = bd(['resolution', '2560x1440', '--hidpi', 'on']);
  assert.equal(bad.code, 1);
  assert.match(bad.out, /no 2560x1440 HiDPI mode/);
  assert.equal(bd(['resolution', '2560x1440', '--hidpi', 'on', '--force']).code, 0);
  assert.equal(disp('32G1WG4').props.hiDPI, 'on');
  assert.match(bd(['resolution']).out, /usage: resolution/);
  assert.match(bd(['resolution', 'big']).out, /resolution must look like/);
});

test('refresh and brightness validation', () => {
  assert.equal(bd(['refresh', '60']).code, 0);
  assert.equal(disp('32G1WG4').props.refreshRate, '60Hz');
  assert.equal(bd(['refresh', '120Hz']).code, 0);
  assert.match(bd(['refresh', 'fast']).out, /refresh rate must look like/);
  assert.equal(bd(['brightness', '40']).code, 0);
  assert.equal(disp('32G1WG4').props.brightness, '0.4');
  assert.match(bd(['brightness', '0']).out, /brightness must be 1-100/);
  assert.match(bd(['brightness', '101']).out, /brightness must be 1-100/);
  assert.match(bd(['brightness', 'dim']).out, /brightness must be 1-100/);
});

test('mirror on needs a worklab virtual screen; on/off round trip', () => {
  assert.match(bd(['mirror', 'on']).out, /no virtual screen to mirror/);
  assert.match(bd(['mirror']).out, /usage: mirror/);
  bd(['preset', 'apply', 'dev', '--yes']);
  assert.equal(bd(['mirror', 'off']).code, 0);
  assert.equal(disp('32G1WG4').props.mirror, 'off');
  assert.equal(bd(['mirror', 'on']).code, 0);
  assert.equal(disp('32G1WG4').props.mirror, 'on');
});

test('--dry-run on simple controls only prints', () => {
  bd(['brightness', '40', '--dry-run']);
  bd(['resolution', '1280x720', '--dry-run']);
  bd(['refresh', '60', '--dry-run']);
  assert.equal(writes().length, 0);
  assert.equal(disp('32G1WG4').props.brightness, '1.0');
});

// ============================================================ user presets

test('user presets are loaded and validated', () => {
  mkdirSync(join(home, '.worklab'), { recursive: true });
  const f = join(home, '.worklab', 'display-presets.json');
  writeFileSync(f, JSON.stringify({ wide: { kind: 'canvas', resolution: '3008x1692', logical: ['1920x1080', '3008x1692'], desc: 'my wide canvas' } }));
  assert.match(bd(['presets']).out, /wide\s+canvas\s+3008x1692 HiDPI/);
  assert.equal(bd(['preset', 'apply', 'wide', '--yes']).code, 0);
  assert.ok(disp('worklab-3008x1692'));

  writeFileSync(f, JSON.stringify({ 'Bad Name': { kind: 'light', brightness: 50 } }));
  assert.match(bd(['presets']).out, /must be lowercase/);
  writeFileSync(f, JSON.stringify({ x: { kind: 'canvas' } }));
  assert.match(bd(['presets']).out, /need a resolution/);
  writeFileSync(f, '{nope');
  assert.match(bd(['presets']).out, /not valid JSON/);
});

test('commands that need the CLI fail clearly when it is missing', () => {
  for (const args of [['status'], ['modes'], ['preset', 'apply', 'dev', '--yes'], ['resolution', '1280x720'], ['brightness', '50'], ['raw', 'get', '--identifiers']]) {
    const r = bd(args, { path: '/usr/bin:/bin' });
    assert.equal(r.code, 1, args.join(' '));
    assert.match(r.out, /betterdisplaycli not found/);
  }
});
