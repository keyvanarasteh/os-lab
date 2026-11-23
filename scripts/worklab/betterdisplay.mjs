#!/usr/bin/env node
// betterdisplay.mjs - display control and presets for the worklab setup (todo section 8, "Phase 4").
//
// Drives BetterDisplay through its `betterdisplaycli` (brew install waydabber/betterdisplay/betterdisplaycli).
// Zero dependencies, Node >= 18, macOS. Every command that changes something supports --dry-run.
//
//   node betterdisplay.mjs help
//
// What it adds over doing it by hand in the UI:
//   - canvas presets: a software 16:9 HiDPI virtual screen mirrored to the physical panel
//     (comfort 2304x1296, dev 2560x1440, max 2880x1620) and `native` to go back
//   - brightness presets (bright / day / evening / night) that combine with a canvas preset: dev+evening
//   - a memory guard: HiDPI canvases are refused while swap is high (the Mac already ran out of memory once)
//   - a snapshot of the original state, so `revert` puts everything back
//   - automatic undo if a step fails halfway
//
// Marked VERIFY: written from the CLI's own help text, not yet exercised against a real virtual screen.
// In particular the mirror direction (see --mirror-source) and the HiDPI resolution list semantics.

import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { homedir, platform } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';

// ================================================================ constants

const STATE_DIR = join(homedir(), '.worklab');
const STATE_FILE = join(STATE_DIR, 'display-state.json');
const USER_PRESETS_FILE = join(STATE_DIR, 'display-presets.json');
const VIRTUAL_PREFIX = 'worklab-'; // only virtual screens with this prefix are ever discarded
const SWAP_LIMIT_MB = 2048; // same budget as worklab.mjs doctor
const CLI = 'betterdisplaycli';

// ================================================================ small utilities

class UserError extends Error {}

const sleep = (s) => {
  if (process.env.WORKLAB_NO_SLEEP) return;
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, s * 1000);
};

class Logger {
  constructor() {
    const on = process.stdout.isTTY && !process.env.NO_COLOR;
    this.paint = (code) => (s) => (on ? `\x1b[${code}m${s}\x1b[0m` : s);
    this.dim = this.paint(2);
    this.red = this.paint(31);
    this.green = this.paint(32);
    this.yellow = this.paint(33);
    this.bold = this.paint(1);
  }
  line(s = '') {
    console.log(s);
  }
  info(s) {
    console.log(`${this.bold('==>')} ${s}`);
  }
  ok(s) {
    console.log(`${this.green('ok')}   ${s}`);
  }
  warn(s) {
    console.log(`${this.yellow('warn')} ${s}`);
  }
  fail(s) {
    console.log(`${this.red('FAIL')} ${s}`);
  }
}

/** Runs external commands. Reads always run; writes only print in dry-run mode. */
class Shell {
  constructor({ dryRun = false, log }) {
    this.dryRun = dryRun;
    this.log = log;
  }
  static fmt(cmd, args) {
    return [cmd, ...args].map((a) => (/[\s"'$`]/.test(a) ? JSON.stringify(a) : a)).join(' ');
  }
  /** Returns { ok, out }. Never throws. */
  read(cmd, args = []) {
    const r = spawnSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
    if (r.error) return { ok: false, out: '', err: r.error.message };
    return { ok: r.status === 0, out: (r.stdout ?? '').trim(), err: (r.stderr ?? '').trim() };
  }
  /** Mutating call. In dry-run it only prints. Returns { ok, out }. */
  write(cmd, args = []) {
    if (this.dryRun) {
      this.log.line(this.log.dim(`[dry-run] ${Shell.fmt(cmd, args)}`));
      return { ok: true, out: '', dry: true };
    }
    this.log.line(this.log.dim(`$ ${Shell.fmt(cmd, args)}`));
    return this.read(cmd, args);
  }
  has(bin) {
    return this.read('/usr/bin/which', [bin]).ok;
  }
}

// ================================================================ value types

class Resolution {
  constructor(width, height) {
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 320 || height < 200 || width > 16384 || height > 16384) {
      throw new UserError(`invalid resolution ${width}x${height}`);
    }
    this.width = width;
    this.height = height;
  }
  static parse(text) {
    const m = /^(\d{3,5})\s*[x×]\s*(\d{3,5})$/i.exec(String(text).trim());
    if (!m) throw new UserError(`resolution must look like 2560x1440, got "${text}"`);
    return new Resolution(Number(m[1]), Number(m[2]));
  }
  toString() {
    return `${this.width}x${this.height}`;
  }
  equals(o) {
    return this.width === o.width && this.height === o.height;
  }
  get aspect() {
    const gcd = (a, b) => (b ? gcd(b, a % b) : a);
    const g = gcd(this.width, this.height);
    return [this.width / g, this.height / g];
  }
  /** Pixels per inch on a panel of the given diagonal, at this logical size. */
  ppi(diagonalInch) {
    return Math.hypot(this.width, this.height) / diagonalInch;
  }
  /** Rough framebuffer memory: HiDPI doubles both axes; 4 bytes per pixel; triple buffered. A planning figure, not a measurement. */
  framebufferMB(hiDPI = true, buffers = 3) {
    const scale = hiDPI ? 2 : 1;
    return Math.round((this.width * scale * this.height * scale * 4 * buffers) / 1024 / 1024);
  }
}

class Display {
  constructor(record) {
    this.name = record.name;
    this.tagID = record.tagID;
    this.uuid = record.UUID;
    this.displayID = record.displayID;
    this.deviceType = record.deviceType;
  }
  get isVirtual() {
    return this.deviceType === 'VirtualScreen';
  }
  get isPhysical() {
    return this.deviceType === 'Display';
  }
  get isWorklab() {
    return this.isVirtual && this.name.startsWith(VIRTUAL_PREFIX);
  }
  /** Selector flags that identify exactly this device. */
  get selector() {
    return { name: this.name };
  }
}

class DisplayMode {
  constructor(index, resolution, hiDPI, hz, depth) {
    Object.assign(this, { index, resolution, hiDPI, hz, depth });
  }
  /** Lines look like "12 - 2560x1440 HiDPI 144Hz 10bpc". */
  static parse(line) {
    const m = /^(\d+)\s*-\s*(\d+x\d+)(\s+HiDPI)?\s+([\d.]+)Hz(?:\s+(\d+bpc))?/i.exec(line.trim());
    return m ? new DisplayMode(Number(m[1]), Resolution.parse(m[2]), Boolean(m[3]), Number(m[4]), m[5] ?? '') : null;
  }
  toString() {
    return `${String(this.index).padStart(3)}  ${this.resolution}${this.hiDPI ? ' HiDPI' : ''} ${this.hz}Hz ${this.depth}`.trimEnd();
  }
}

// ================================================================ BetterDisplay CLI wrapper

class BetterDisplayCli {
  constructor(shell, bin = CLI) {
    this.shell = shell;
    this.bin = bin;
  }

  /** { name: 'X', type: 'VirtualScreen' } -> ['--name=X', '--type=VirtualScreen']. true -> bare flag. */
  static flags(obj = {}) {
    return Object.entries(obj)
      .filter(([, v]) => v !== undefined && v !== null && v !== false)
      .map(([k, v]) => (v === true ? `--${k}` : `--${k}=${v}`));
  }

  get installed() {
    return this.shell.has(this.bin);
  }

  requireInstalled() {
    if (!this.installed) throw new UserError(`${this.bin} not found. Install: brew install waydabber/betterdisplay/betterdisplaycli (and enable CLI integration in BetterDisplay settings)`);
  }

  /** Read a feature. Returns a trimmed string or null when BetterDisplay says "Failed." */
  get(selector, feature, extra = {}) {
    const r = this.shell.read(this.bin, ['get', ...BetterDisplayCli.flags(selector), ...BetterDisplayCli.flags({ [feature]: true, ...extra })]);
    if (!r.ok || r.out === 'Failed.' || r.out === '') return null;
    return r.out;
  }

  getBool(selector, feature) {
    const v = this.get(selector, feature);
    if (v === null) return null;
    return /^(on|true|1)$/i.test(v);
  }

  /** Mutating set. Throws UserError on failure so callers can undo. */
  set(selector, features) {
    return this.#write('set', selector, features);
  }

  create(type, props) {
    return this.#write('create', { type }, props);
  }

  /** discard without an identifier would delete EVERY discardable device. Refuse that here. */
  discard(selector) {
    if (!selector.name && !selector.tagID && !selector.UUID) throw new UserError('refusing to discard without name, tagID or UUID');
    if (selector.name && !selector.name.startsWith(VIRTUAL_PREFIX)) throw new UserError(`refusing to discard "${selector.name}": not a ${VIRTUAL_PREFIX}* screen`);
    return this.#write('discard', { type: 'VirtualScreen', ...selector }, {});
  }

  #write(op, selector, features) {
    const args = [op, ...BetterDisplayCli.flags(selector), ...BetterDisplayCli.flags(features)];
    const r = this.shell.write(this.bin, args);
    if (!r.ok || r.out === 'Failed.') throw new UserError(`${Shell.fmt(this.bin, args)} failed${r.out ? `: ${r.out}` : r.err ? `: ${r.err}` : ''}`);
    return r;
  }

  /** `get --identifiers` prints bare objects separated by commas; wrap them to parse. */
  identifiers() {
    const r = this.shell.read(this.bin, ['get', '--identifiers']);
    if (!r.ok || !r.out || r.out === 'Failed.') return [];
    try {
      return JSON.parse(`[${r.out}]`).map((rec) => new Display(rec)).filter((d) => d.isPhysical || d.isVirtual);
    } catch {
      throw new UserError(`could not parse the display list from BetterDisplay: ${r.out.slice(0, 120)}`);
    }
  }

  modes(selector) {
    const out = this.get(selector, 'displayModeList');
    return (out ?? '').split('\n').map(DisplayMode.parse).filter(Boolean);
  }

  proAvailable() {
    return this.get({}, 'proAvailable') === 'on';
  }
}

// ================================================================ inventory and snapshot

class DisplayInventory {
  constructor(cli) {
    this.cli = cli;
    this.displays = [];
  }
  refresh() {
    this.displays = this.cli.identifiers();
    return this;
  }
  get physical() {
    return this.displays.filter((d) => d.isPhysical);
  }
  get virtual() {
    return this.displays.filter((d) => d.isVirtual);
  }
  get worklabScreens() {
    return this.displays.filter((d) => d.isWorklab);
  }
  find(name) {
    return this.displays.find((d) => d.name === name) ?? null;
  }
  /** The display presets act on: --display, else the main physical display, else the only physical one. */
  primary(name) {
    if (name) {
      const d = this.find(name);
      if (!d) throw new UserError(`no display named "${name}". Known: ${this.displays.map((x) => x.name).join(', ') || '(none)'}`);
      return d;
    }
    const phys = this.physical;
    if (!phys.length) throw new UserError('no physical display found. Is BetterDisplay running with CLI integration enabled?');
    return phys.find((d) => this.cli.getBool(d.selector, 'main')) ?? phys[0];
  }
}

/** The state before the first preset was applied. Kept until `revert`, so repeated applies never lose the original. */
class StateStore {
  constructor(file = STATE_FILE) {
    this.file = file;
  }
  load() {
    if (!existsSync(this.file)) return null;
    try {
      return JSON.parse(readFileSync(this.file, 'utf8'));
    } catch {
      return null;
    }
  }
  /** First snapshot wins. */
  saveOnce(snapshot) {
    if (this.load()) return false;
    mkdirSync(STATE_DIR, { recursive: true });
    writeFileSync(this.file, JSON.stringify(snapshot, null, 2));
    return true;
  }
  update(patch) {
    const cur = this.load();
    if (!cur) return;
    writeFileSync(this.file, JSON.stringify({ ...cur, ...patch }, null, 2));
  }
  clear() {
    if (existsSync(this.file)) unlinkSync(this.file);
  }
}

// ================================================================ health guard

class HealthGuard {
  constructor(shell, { swapLimitMB = SWAP_LIMIT_MB } = {}) {
    this.shell = shell;
    this.swapLimitMB = swapLimitMB;
  }
  swapUsedMB() {
    if (process.env.WORKLAB_SWAP_MB) return Number(process.env.WORKLAB_SWAP_MB); // test hook
    const r = this.shell.read('sysctl', ['-n', 'vm.swapusage']);
    const m = /used = ([\d.]+)([MG])/.exec(r.out);
    return m ? Number(m[1]) * (m[2] === 'G' ? 1024 : 1) : 0;
  }
  /** { ok, swapMB, reason } */
  check() {
    const swapMB = this.swapUsedMB();
    return swapMB <= this.swapLimitMB
      ? { ok: true, swapMB }
      : { ok: false, swapMB, reason: `swap used is ${Math.round(swapMB)} MB (limit ${this.swapLimitMB} MB). A HiDPI canvas adds framebuffer memory. Restart or close heavy apps, or pass --force.` };
  }
}

// ================================================================ presets and plans

/** One unit of work with an optional undo. */
class Step {
  constructor(label, run, undo = null) {
    this.label = label;
    this.run = run;
    this.undo = undo;
  }
}

class Plan {
  constructor(steps = []) {
    this.steps = steps;
  }
  get labels() {
    return this.steps.map((s) => s.label);
  }
  /** Runs steps in order; if one throws, undoes the completed ones in reverse and rethrows. */
  execute(log) {
    const done = [];
    try {
      for (const step of this.steps) {
        log.info(step.label);
        step.run();
        done.push(step);
      }
    } catch (e) {
      log.warn(`failed: ${e.message}`);
      log.warn('undoing completed steps');
      for (const step of done.reverse()) {
        if (!step.undo) continue;
        try {
          step.undo();
        } catch (u) {
          log.warn(`undo of "${step.label}" failed: ${u.message}`);
        }
      }
      throw e;
    }
  }
}

/**
 * kind: 'canvas' (virtual screen mirrored to the panel), 'native' (no virtual screen), 'light' (brightness only).
 * `logical` is the resolution list the virtual screen offers; `resolution` is the one it starts at.
 */
class Preset {
  constructor(name, def) {
    this.name = name;
    this.desc = def.desc ?? '';
    this.kind = def.kind ?? 'canvas';
    if (!['canvas', 'native', 'light'].includes(this.kind)) throw new UserError(`preset "${name}": unknown kind "${this.kind}"`);
    this.resolution = def.resolution ? Resolution.parse(def.resolution) : null;
    this.logical = (def.logical ?? (this.resolution ? [this.resolution.toString()] : [])).map((r) => Resolution.parse(r));
    this.hiDPI = def.hiDPI ?? this.kind === 'canvas';
    this.sizeInch = def.sizeInch ?? null;
    this.brightness = def.brightness ?? null;
    this.heavy = def.heavy ?? this.kind === 'canvas';
    if (this.kind === 'canvas' && !this.resolution) throw new UserError(`preset "${name}": canvas presets need a resolution`);
    if (this.brightness !== null && !(this.brightness >= 1 && this.brightness <= 100)) throw new UserError(`preset "${name}": brightness must be 1-100`);
    if (this.kind === 'light' && this.brightness === null) throw new UserError(`preset "${name}": light presets need a brightness`);
  }
  /** Name of the virtual screen this preset needs. */
  get virtualName() {
    return `${VIRTUAL_PREFIX}${this.resolution.width}x${this.resolution.height}`;
  }
  describe(sizeInch = 32) {
    if (this.kind === 'light') return `brightness ${this.brightness}%`;
    if (this.kind === 'native') return `native ${this.resolution ?? '1920x1080'}, no virtual screen`;
    const ppi = Math.round(this.resolution.ppi(this.sizeInch ?? sizeInch));
    return `${this.resolution} HiDPI (~${ppi} PPI at ${this.sizeInch ?? sizeInch}", ~${this.resolution.framebufferMB(true)} MB framebuffer)`;
  }
}

const BUILTIN_PRESETS = {
  native: { kind: 'native', resolution: '1920x1080', hiDPI: false, desc: 'Native 1080p, mirroring off, worklab virtual screens removed' },
  comfort: {
    kind: 'canvas',
    resolution: '2304x1296',
    logical: ['1920x1080', '2304x1296'],
    desc: 'Larger text, 44% more room than 1080p. Easiest on memory.',
  },
  dev: {
    kind: 'canvas',
    resolution: '2560x1440',
    logical: ['1920x1080', '2304x1296', '2560x1440'],
    desc: 'Room for a 3-pane layout or 2x2 agents grid (the todo target).',
  },
  max: {
    kind: 'canvas',
    resolution: '2880x1620',
    logical: ['1920x1080', '2560x1440', '2880x1620'],
    desc: 'Most room, smallest text. Heaviest framebuffer.',
  },
  bright: { kind: 'light', brightness: 100, desc: 'Brightness 100%' },
  day: { kind: 'light', brightness: 80, desc: 'Brightness 80%' },
  evening: { kind: 'light', brightness: 55, desc: 'Brightness 55%' },
  night: { kind: 'light', brightness: 30, desc: 'Brightness 30%' },
};

class PresetRegistry {
  constructor(userFile = USER_PRESETS_FILE) {
    this.presets = new Map(Object.entries(BUILTIN_PRESETS).map(([n, d]) => [n, new Preset(n, d)]));
    if (existsSync(userFile)) {
      let user;
      try {
        user = JSON.parse(readFileSync(userFile, 'utf8'));
      } catch (e) {
        throw new UserError(`${userFile} is not valid JSON: ${e.message}`);
      }
      for (const [n, d] of Object.entries(user)) {
        if (!/^[a-z0-9][a-z0-9-]*$/.test(n)) throw new UserError(`${userFile}: preset name "${n}" must be lowercase letters, digits and dashes`);
        this.presets.set(n, new Preset(n, d));
      }
    }
  }
  get(name) {
    const p = this.presets.get(name);
    if (!p) throw new UserError(`unknown preset "${name}". Known: ${[...this.presets.keys()].join(', ')}`);
    return p;
  }
  /** "dev+evening" -> [dev, evening]. At most one canvas/native preset and one light preset. */
  resolve(spec) {
    const parts = spec.split('+').map((s) => s.trim()).filter(Boolean).map((n) => this.get(n));
    if (!parts.length) throw new UserError('no preset given');
    const base = parts.filter((p) => p.kind !== 'light');
    const light = parts.filter((p) => p.kind === 'light');
    if (base.length > 1) throw new UserError(`"${spec}" has more than one canvas preset (${base.map((p) => p.name).join(', ')}); combine one canvas with one brightness preset`);
    if (light.length > 1) throw new UserError(`"${spec}" has more than one brightness preset`);
    return { base: base[0] ?? null, light: light[0] ?? null };
  }
  list() {
    return [...this.presets.values()];
  }
}

// ================================================================ manager

class DisplayManager {
  constructor({ cli, inventory, store, guard, shell, log, opts }) {
    Object.assign(this, { cli, inventory, store, guard, shell, log, opts });
  }

  get dryRun() {
    return this.shell.dryRun;
  }

  // ---------------------------------------------------------- reading

  describeDisplay(d) {
    const sel = d.selector;
    const bright = this.cli.get(sel, 'brightness');
    return {
      name: d.name,
      kind: d.deviceType,
      main: this.cli.getBool(sel, 'main'),
      resolution: this.cli.get(sel, 'resolution'),
      hiDPI: this.cli.getBool(sel, 'hiDPI'),
      refresh: this.cli.get(sel, 'refreshRate'),
      brightnessPct: bright === null ? null : Math.round(Number(bright) * 100),
      mirror: this.cli.getBool(sel, 'mirror'),
      connected: this.cli.getBool(sel, 'connected'),
    };
  }

  status() {
    this.inventory.refresh();
    const L = this.log;
    L.info('Displays');
    if (!this.inventory.displays.length) L.line('  (none reported; is BetterDisplay running with CLI integration enabled?)');
    for (const d of this.inventory.displays) {
      const s = this.describeDisplay(d);
      const bits = [
        s.main ? 'main' : null,
        s.resolution ? `${s.resolution}${s.hiDPI ? ' HiDPI' : ''}` : null,
        s.refresh,
        s.brightnessPct !== null ? `brightness ${s.brightnessPct}%` : null,
        s.mirror !== null ? `mirror ${s.mirror ? 'on' : 'off'}` : null,
      ].filter(Boolean);
      L.line(`  ${d.isVirtual ? 'virtual ' : 'physical'}  ${d.name}  ${L.dim(bits.join(' | '))}`);
    }
    const st = this.store.load();
    L.line(`  active preset: ${st?.applied ?? 'none'}${st ? L.dim('  (revert restores the original state)') : ''}`);
    const h = this.guard.check();
    L.line(`  swap used: ${Math.round(h.swapMB)} MB (limit ${this.guard.swapLimitMB} MB) ${h.ok ? L.green('ok') : L.yellow('high')}`);
  }

  modes({ display, hidpi, filter } = {}) {
    this.inventory.refresh();
    const d = this.inventory.primary(display);
    let modes = this.cli.modes(d.selector);
    if (hidpi !== undefined) modes = modes.filter((m) => m.hiDPI === (hidpi === 'on'));
    if (filter) modes = modes.filter((m) => `${m.resolution}`.includes(filter) || `${m.hz}Hz`.includes(filter));
    this.log.info(`${modes.length} mode(s) on ${d.name}`);
    for (const m of modes) this.log.line(`  ${m}`);
  }

  // ---------------------------------------------------------- simple controls

  setResolution(text, { display, hidpi } = {}) {
    this.inventory.refresh();
    const d = this.inventory.primary(display);
    const res = Resolution.parse(text);
    const wantHiDPI = hidpi === undefined ? undefined : hidpi === 'on';
    if (!this.opts.force) {
      const modes = this.cli.modes(d.selector);
      if (modes.length && !modes.some((m) => m.resolution.equals(res) && (wantHiDPI === undefined || m.hiDPI === wantHiDPI))) {
        throw new UserError(`${d.name} has no ${res}${wantHiDPI ? ' HiDPI' : ''} mode. See: modes${display ? ` --display ${display}` : ''} --filter ${res.width}`);
      }
    }
    this.cli.set(d.selector, { resolution: res.toString(), ...(wantHiDPI === undefined ? {} : { hiDPI: wantHiDPI ? 'on' : 'off' }) });
    this.log.ok(`${d.name} -> ${res}${wantHiDPI ? ' HiDPI' : ''}`);
  }

  setRefresh(rate, { display } = {}) {
    this.inventory.refresh();
    const d = this.inventory.primary(display);
    if (!/^[\d.]+(hz)?(-vrr)?$/i.test(rate) && !/^\d+-\d+hz$/i.test(rate)) throw new UserError(`refresh rate must look like 144 or 60Hz, got "${rate}"`);
    this.cli.set(d.selector, { refreshRate: /hz/i.test(rate) ? rate : `${rate}Hz` });
    this.log.ok(`${d.name} refresh -> ${rate}`);
  }

  setBrightness(pct, { display } = {}) {
    const n = Number(pct);
    if (!Number.isFinite(n) || n < 1 || n > 100) throw new UserError('brightness must be 1-100 (0 is refused so the screen cannot go black)');
    this.inventory.refresh();
    const d = this.inventory.primary(display);
    this.cli.set(d.selector, { brightness: `${n}%` });
    this.log.ok(`${d.name} brightness -> ${n}%`);
  }

  // ---------------------------------------------------------- virtual screens and mirroring

  listVirtual() {
    this.inventory.refresh();
    const v = this.inventory.virtual;
    this.log.info(`${v.length} virtual screen(s)`);
    for (const d of v) this.log.line(`  ${d.name}${d.isWorklab ? '' : this.log.dim('  (not managed by worklab)')}`);
  }

  createVirtual(preset, { sizeInch = 32 } = {}) {
    const res = preset.resolution;
    const [aw, ah] = res.aspect;
    const list = [...new Set([...preset.logical.map(String), res.toString()])];
    this.cli.create('VirtualScreen', {
      virtualScreenName: preset.virtualName,
      aspectWidth: aw,
      aspectHeight: ah,
      sizeInch: preset.sizeInch ?? sizeInch,
      virtualScreenHiDPI: preset.hiDPI ? 'on' : 'off',
      useResolutionList: 'on',
      resolutionList: list.join(','),
    });
  }

  mirror(on, { display, target } = {}) {
    this.inventory.refresh();
    const phys = this.inventory.primary(display);
    if (on) {
      const tgt = target ? this.inventory.find(target) : this.inventory.worklabScreens[0];
      if (!tgt) throw new UserError('no virtual screen to mirror with. Create one: preset apply dev');
      this.#mirrorPair(phys, tgt, true);
    } else {
      this.cli.set(phys.selector, { mirror: 'off' });
      for (const v of this.inventory.virtual) if (this.cli.getBool(v.selector, 'mirror')) this.cli.set(v.selector, { mirror: 'off' });
    }
    this.log.ok(`mirror ${on ? 'on' : 'off'}`);
  }

  #mirrorPair(physical, virtual, on) {
    // Default: the physical panel mirrors the virtual screen (the panel shows the HiDPI canvas).
    // VERIFY on a real setup; `--mirror-source physical` flips the direction.
    const [follower, source] = this.opts.mirrorSource === 'physical' ? [virtual, physical] : [physical, virtual];
    this.cli.set(follower.selector, { mirror: on ? 'on' : 'off', targetName: source.name });
  }

  // ---------------------------------------------------------- presets

  /** Build the plan for `spec` (e.g. "dev+evening") without running anything. */
  plan(spec) {
    const { base, light } = this.presetsFor(spec);
    this.inventory.refresh();
    const phys = this.inventory.primary(this.opts.display);
    const steps = [];

    if (base?.kind === 'canvas') steps.push(...this.#canvasSteps(base, phys));
    if (base?.kind === 'native') steps.push(...this.#nativeSteps(base, phys));
    if (light) steps.push(this.#brightnessStep(light.brightness, phys));
    if (base?.brightness) steps.push(this.#brightnessStep(base.brightness, phys));
    return { base, light, phys, plan: new Plan(steps) };
  }

  presetsFor(spec) {
    return new PresetRegistry(this.opts.userPresetsFile ?? USER_PRESETS_FILE).resolve(spec);
  }

  #brightnessStep(pct, phys) {
    const prev = this.cli.get(phys.selector, 'brightness');
    return new Step(
      `brightness ${pct}% on ${phys.name}`,
      () => this.cli.set(phys.selector, { brightness: `${pct}%` }),
      prev === null ? null : () => this.cli.set(phys.selector, { brightness: prev }),
    );
  }

  #canvasSteps(preset, phys) {
    const name = preset.virtualName;
    const existing = this.inventory.find(name);
    const steps = [];

    // Remove any other worklab canvas first (switching dev -> comfort), after un-mirroring.
    const stale = this.inventory.worklabScreens.filter((d) => d.name !== name);
    if (stale.length || (existing && this.cli.getBool(phys.selector, 'mirror'))) {
      steps.push(new Step(`mirror off on ${phys.name}`, () => this.cli.set(phys.selector, { mirror: 'off' })));
    }
    for (const d of stale) steps.push(new Step(`remove old virtual screen ${d.name}`, () => this.cli.discard({ name: d.name })));

    if (!existing) {
      steps.push(
        new Step(
          `create virtual screen ${name} (${preset.resolution} HiDPI, list ${[...new Set([...preset.logical.map(String), preset.resolution.toString()])].join(', ')})`,
          () => {
            this.createVirtual(preset, { sizeInch: this.opts.sizeInch });
            sleep(1.5);
            if (!this.dryRun && !this.inventory.refresh().find(name)) throw new UserError(`${name} did not appear after create`);
          },
          () => this.cli.discard({ name }),
        ),
      );
    }

    steps.push(
      new Step(`set ${name} to ${preset.resolution}${preset.hiDPI ? ' HiDPI' : ''}`, () => {
        this.cli.set({ name }, { resolution: preset.resolution.toString(), hiDPI: preset.hiDPI ? 'on' : 'off' });
        sleep(1);
      }),
    );

    steps.push(
      new Step(
        `mirror: ${this.opts.mirrorSource === 'physical' ? `${name} follows ${phys.name}` : `${phys.name} follows ${name}`}`,
        () => {
          this.#mirrorPair(phys, { name, selector: { name } }, true);
          sleep(1.5);
        },
        () => this.cli.set(phys.selector, { mirror: 'off' }),
      ),
      new Step('verify', () => this.#verifyCanvas(preset, phys)),
    );
    return steps;
  }

  #nativeSteps(preset, phys) {
    const steps = [];
    const screens = this.inventory.worklabScreens;
    if (this.cli.getBool(phys.selector, 'mirror') || screens.length) {
      steps.push(new Step(`mirror off on ${phys.name}`, () => this.cli.set(phys.selector, { mirror: 'off' })));
    }
    for (const d of screens) steps.push(new Step(`remove virtual screen ${d.name}`, () => this.cli.discard({ name: d.name })));
    const res = preset.resolution ?? Resolution.parse('1920x1080');
    steps.push(
      new Step(`set ${phys.name} to ${res}`, () => {
        sleep(1);
        this.cli.set(phys.selector, { resolution: res.toString(), hiDPI: 'off' });
      }),
    );
    return steps;
  }

  #verifyCanvas(preset, phys) {
    if (this.dryRun) return;
    const name = preset.virtualName;
    const physMirror = this.cli.getBool(phys.selector, 'mirror');
    const virtMirror = this.cli.getBool({ name }, 'mirror');
    if (!physMirror && !virtMirror) throw new UserError('mirroring did not take effect (neither screen reports mirror on)');
    if (this.opts.mirrorSource !== 'physical' && !physMirror && virtMirror) {
      this.log.warn(`${name} is the follower, not ${phys.name}. If the panel does not show the larger canvas, re-run with --mirror-source physical (VERIFY).`);
    }
    const got = this.cli.get({ name }, 'resolution');
    if (got && got !== preset.resolution.toString()) this.log.warn(`${name} reports ${got}, wanted ${preset.resolution}`);
    // A virtual screen that is NOT mirrored would look like a second monitor to AeroSpace.
    const mon = this.shell.has('aerospace') ? Number(this.shell.read('aerospace', ['list-monitors', '--count']).out) : null;
    if (mon !== null && mon > 1) this.log.warn(`AeroSpace sees ${mon} monitors; the virtual screen may be acting as a second monitor. Run: revert`);
  }

  apply(spec) {
    const L = this.log;
    this.cli.requireInstalled();
    const { base, light, phys, plan } = this.plan(spec);

    if (base?.kind === 'canvas' && !this.opts.force) {
      const h = this.guard.check();
      if (!h.ok) throw new UserError(h.reason);
    }
    if (base?.kind === 'canvas') {
      const inch = this.opts.sizeInch ?? base.sizeInch ?? 32;
      L.info(`Preset ${spec}: ${[base, light].filter(Boolean).map((p) => `${p.name} (${p.describe(inch)})`).join(' + ')}`);
    } else L.info(`Preset ${spec}: ${[base, light].filter(Boolean).map((p) => `${p.name} (${p.describe()})`).join(' + ')}`);

    if (!plan.steps.length) return L.ok('nothing to do');

    if (!this.dryRun) {
      const snap = this.#snapshot(phys);
      if (this.store.saveOnce(snap)) L.ok(`saved original state to ${this.store.file}`);
    }
    plan.execute(L);
    if (!this.dryRun) this.store.update({ applied: spec });
    L.ok(`preset ${spec} applied. Undo with: node betterdisplay.mjs revert`);
    if (base?.kind === 'canvas') L.line('Watch `sysctl vm.swapusage` and WindowServer memory for a day. If swap climbs: revert.');
  }

  #snapshot(phys) {
    const s = this.describeDisplay(phys);
    return {
      takenAt: new Date().toISOString(),
      display: phys.name,
      resolution: s.resolution,
      hiDPI: s.hiDPI,
      refresh: s.refresh,
      brightnessPct: s.brightnessPct,
      mirror: s.mirror,
      applied: null,
    };
  }

  revert() {
    const L = this.log;
    this.cli.requireInstalled();
    const snap = this.store.load();
    this.inventory.refresh();
    const phys = this.inventory.find(snap?.display ?? '') ?? this.inventory.primary(this.opts.display);
    L.info(snap ? `Reverting to the state saved ${snap.takenAt}` : 'No saved state; going to native 1080p and removing worklab virtual screens');

    if (this.cli.getBool(phys.selector, 'mirror') || this.inventory.worklabScreens.length) this.cli.set(phys.selector, { mirror: 'off' });
    for (const d of this.inventory.worklabScreens) this.cli.discard({ name: d.name });
    sleep(1);

    const res = snap?.resolution ?? '1920x1080';
    this.cli.set(phys.selector, { resolution: res, hiDPI: snap?.hiDPI ? 'on' : 'off' });
    if (snap?.refresh) this.#tryRestore(() => this.cli.set(phys.selector, { refreshRate: snap.refresh }), 'refresh rate');
    if (snap?.brightnessPct) this.cli.set(phys.selector, { brightness: `${snap.brightnessPct}%` });
    if (!this.dryRun) this.store.clear();
    L.ok(`reverted: ${phys.name} ${res}${snap?.hiDPI ? ' HiDPI' : ''}`);
  }

  #tryRestore(fn, what) {
    try {
      fn();
    } catch (e) {
      this.log.warn(`could not restore ${what}: ${e.message}`);
    }
  }

  // ---------------------------------------------------------- doctor

  doctor() {
    const L = this.log;
    L.info('BetterDisplay doctor');
    let problems = 0;
    const bad = (m) => {
      L.fail(m);
      problems++;
    };

    if (platform() !== 'darwin') bad('macOS only');
    if (!this.cli.installed) {
      bad(`${CLI} not found: brew install waydabber/betterdisplay/betterdisplaycli`);
      return problems;
    }
    L.ok(`${CLI} found`);

    this.inventory.refresh();
    if (!this.inventory.displays.length) bad('BetterDisplay returned no displays: start the app and enable Settings -> Integration -> command line');
    else L.ok(`${this.inventory.physical.length} physical, ${this.inventory.virtual.length} virtual display(s)`);

    const pro = this.cli.proAvailable();
    pro ? L.ok('Pro features available') : L.warn('Pro features not available (basic mirroring and virtual screens may still work; connection management and associations need Pro)');

    const procs = this.shell.read('ps', ['-axo', 'pid=,command=']).out.split('\n').filter((l) => /BetterDisplay\.app\/Contents\/MacOS\/BetterDisplay(\s|$)/.test(l));
    if (procs.length > 1) bad(`${procs.length} BetterDisplay instances running (${procs.map((l) => l.trim().split(/\s+/)[0]).join(', ')}); two copies fight over displays. Quit the extra one.`);
    else L.ok('single BetterDisplay instance');

    if (this.shell.has('aerospace')) {
      const mon = Number(this.shell.read('aerospace', ['list-monitors', '--count']).out);
      mon > 1 ? L.warn(`AeroSpace sees ${mon} monitors; workspaces are per monitor. Intended only if mirroring is off.`) : L.ok('AeroSpace sees 1 monitor');
    }

    const h = this.guard.check();
    h.ok ? L.ok(`swap ${Math.round(h.swapMB)} MB (limit ${this.guard.swapLimitMB} MB)`) : L.warn(h.reason);

    const stale = this.inventory.worklabScreens;
    if (stale.length) L.warn(`worklab virtual screens present: ${stale.map((d) => d.name).join(', ')}`);
    const st = this.store.load();
    if (st) L.warn(`a preset is active (${st.applied ?? 'unknown'}); revert restores the original state`);

    L.line();
    L.line(problems ? L.yellow(`${problems} problem(s).`) : L.green('Looks good.'));
    return problems;
  }
}

// ================================================================ CLI

const OPTIONS = {
  'dry-run': { type: 'boolean', short: 'n' },
  yes: { type: 'boolean', short: 'y' },
  force: { type: 'boolean' },
  help: { type: 'boolean', short: 'h' },
  display: { type: 'string' },
  target: { type: 'string' },
  hidpi: { type: 'string' },
  filter: { type: 'string' },
  'size-inch': { type: 'string' },
  'mirror-source': { type: 'string' }, // virtual (default) | physical
};

const HELP = (registry) => `betterdisplay.mjs - display control and presets (BetterDisplay CLI) for the worklab setup

usage: node betterdisplay.mjs <command> [args] [options]

commands
  status                         displays, resolution, HiDPI, refresh, brightness, mirror, swap
  doctor                         CLI present, app running, single instance, Pro, AeroSpace monitors, swap
  modes                          list display modes (--hidpi on|off, --filter 2560, --display <name>)
  presets                        list presets
  preset show <name>             print a preset
  preset apply <a[+b]>           apply a canvas/native preset, optionally plus a brightness preset: dev+evening
  revert                         restore the state saved before the first apply
  resolution <WxH>               set resolution of the main panel (--hidpi on|off)
  refresh <Hz>                   set refresh rate, e.g. 144 or 60Hz
  brightness <1-100>             set brightness
  mirror on|off                  mirror the panel with the worklab virtual screen (--target <name>)
  virtual list                   list virtual screens
  raw get <args...>              read-only passthrough to betterdisplaycli get

presets
${registry.list().map((p) => `  ${p.name.padEnd(8)} ${p.kind.padEnd(7)} ${p.desc}`).join('\n')}

options
  -n, --dry-run                  print every change, do nothing
  -y, --yes                      skip confirmations
      --force                    ignore the swap guard and the mode-list check
      --display <name>           act on this display instead of the main physical one
      --size-inch <n>            panel diagonal for PPI math and the virtual screen (default 32)
      --mirror-source virtual|physical   which side follows the other (default: panel follows virtual; VERIFY)

examples
  node betterdisplay.mjs doctor
  node betterdisplay.mjs preset apply dev --dry-run
  node betterdisplay.mjs preset apply comfort+evening
  node betterdisplay.mjs revert

own presets: ${USER_PRESETS_FILE}
  { "wide": { "kind": "canvas", "resolution": "3008x1692", "logical": ["1920x1080","3008x1692"], "desc": "..." } }
`;

async function confirm(question, { yes, dryRun }) {
  if (yes || dryRun) return true;
  if (!process.stdin.isTTY) throw new UserError(`"${question}" needs confirmation. Re-run with --yes (or --dry-run to preview).`);
  const { createInterface } = await import('node:readline/promises');
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const a = (await rl.question(`${question} [y/N] `)).trim().toLowerCase();
  rl.close();
  return a === 'y' || a === 'yes';
}

async function main(argv) {
  const log = new Logger();
  let parsed;
  try {
    parsed = parseArgs({ args: argv, options: OPTIONS, allowPositionals: true });
  } catch (e) {
    throw new UserError(`${e.message.replace(/\.$/, '')}. Try: node betterdisplay.mjs help`);
  }
  const { values: f, positionals } = parsed;
  const [cmd = 'help', ...rest] = positionals;
  const dryRun = Boolean(f['dry-run']);
  const shell = new Shell({ dryRun, log });
  const registry = new PresetRegistry();

  if (f.help || cmd === 'help') return log.line(HELP(registry));
  if (dryRun) log.line(log.yellow('DRY RUN: nothing will be changed.'));

  const mirrorSource = f['mirror-source'] ?? 'virtual';
  if (!['virtual', 'physical'].includes(mirrorSource)) throw new UserError('--mirror-source must be virtual or physical');
  if (f.hidpi !== undefined && !['on', 'off'].includes(f.hidpi)) throw new UserError('--hidpi must be on or off');
  const sizeInch = f['size-inch'] === undefined ? undefined : Number(f['size-inch']);
  if (sizeInch !== undefined && !(sizeInch >= 5 && sizeInch <= 100)) throw new UserError('--size-inch must be 5-100');

  const cli = new BetterDisplayCli(shell);
  const mgr = new DisplayManager({
    cli,
    shell,
    log,
    inventory: new DisplayInventory(cli),
    store: new StateStore(),
    guard: new HealthGuard(shell),
    opts: { force: Boolean(f.force), display: f.display, mirrorSource, sizeInch },
  });

  const needsCli = () => cli.requireInstalled();
  const needArg = (v, usage) => {
    if (v === undefined) throw new UserError(`usage: ${usage}`);
    return v;
  };

  switch (cmd) {
    case 'status':
      needsCli();
      return mgr.status();
    case 'doctor':
      return void mgr.doctor();
    case 'modes':
      needsCli();
      return mgr.modes({ display: f.display, hidpi: f.hidpi, filter: f.filter });
    case 'presets':
      for (const p of registry.list()) log.line(`  ${p.name.padEnd(8)} ${p.kind.padEnd(7)} ${p.describe(sizeInch ?? 32).padEnd(52)} ${p.desc}`);
      return;
    case 'preset': {
      const [sub = 'list', name] = rest;
      if (sub === 'list') return main(['presets']);
      if (sub === 'show') {
        const p = registry.get(needArg(name, 'preset show <name>'));
        return log.line(JSON.stringify({ name: p.name, kind: p.kind, desc: p.desc, resolution: String(p.resolution ?? ''), logical: p.logical.map(String), hiDPI: p.hiDPI, brightness: p.brightness, framebufferMB: p.resolution?.framebufferMB(p.hiDPI) ?? null }, null, 2));
      }
      if (sub === 'apply') {
        const spec = needArg(name, 'preset apply <name[+name]>');
        needsCli();
        registry.resolve(spec);
        if (!(await confirm(`Apply preset "${spec}" (changes display configuration; screen may flicker)?`, { yes: f.yes, dryRun }))) return log.line('Cancelled.');
        return mgr.apply(spec);
      }
      throw new UserError('preset: use list | show <name> | apply <name[+name]>');
    }
    case 'revert':
      if (!(await confirm('Revert to the original display state?', { yes: f.yes, dryRun }))) return log.line('Cancelled.');
      return mgr.revert();
    case 'resolution':
      needsCli();
      return mgr.setResolution(needArg(rest[0], 'resolution <WxH> [--hidpi on|off]'), { display: f.display, hidpi: f.hidpi });
    case 'refresh':
      needsCli();
      return mgr.setRefresh(needArg(rest[0], 'refresh <Hz>'), { display: f.display });
    case 'brightness':
      needsCli();
      return mgr.setBrightness(needArg(rest[0], 'brightness <1-100>'), { display: f.display });
    case 'mirror':
      needsCli();
      if (!['on', 'off'].includes(rest[0])) throw new UserError('usage: mirror on|off [--target <virtual name>]');
      return mgr.mirror(rest[0] === 'on', { display: f.display, target: f.target });
    case 'virtual':
      needsCli();
      if (rest[0] === 'list' || rest[0] === undefined) return mgr.listVirtual();
      throw new UserError('virtual: use list (create and remove happen through presets so only worklab-* screens are touched)');
    case 'raw': {
      needsCli();
      const [verb, ...args] = rest;
      if (verb !== 'get') throw new UserError('raw only passes through `get`; changes go through the dedicated commands');
      // Anything the CLI does not understand as an operation makes it launch ANOTHER BetterDisplay instance
      // (this happened with a bare --version), so only well-formed --feature[=value] arguments go through.
      const bad = args.find((a) => !/^--[A-Za-z][A-Za-z0-9]*(=[^\s]*)?$/.test(a) || /^--(version|help)$/i.test(a));
      if (bad) throw new UserError(`raw get: "${bad}" is not an accepted argument (use --feature or --feature=value)`);
      const r = shell.read(CLI, ['get', ...args]);
      return log.line(r.out || r.err || '(no output)');
    }
    default:
      throw new UserError(`unknown command "${cmd}". Try: node betterdisplay.mjs help`);
  }
}

// Exported for tests and for reuse; runs only when executed directly.
export { Resolution, Display, DisplayMode, Preset, PresetRegistry, BetterDisplayCli, DisplayManager, Plan, Step, HealthGuard, StateStore };

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('betterdisplay.mjs')) {
  main(process.argv.slice(2)).catch((e) => {
    if (e instanceof UserError) {
      console.error(`error: ${e.message}`);
      process.exit(1);
    }
    throw e;
  });
}
