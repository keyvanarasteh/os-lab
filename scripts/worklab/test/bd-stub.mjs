#!/usr/bin/env node
// Stateful stub for betterdisplaycli, plus tiny stubs for aerospace and ps. Used by betterdisplay.test.mjs.
// State lives in $STUB_DIR/bd.json; every call is appended to $STUB_LOG.
//   BD_FAIL=<feature>   make `set`/`create` fail when that feature is among the args
//   BD_PRO=off          proAvailable returns off
//   BD_PS=<text>        output of `ps`
//   STUB_MONITORS=<n>   aerospace list-monitors --count
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [name, ...args] = process.argv.slice(2);
const dir = process.env.STUB_DIR;
appendFileSync(process.env.STUB_LOG, `${name} ${args.join(' ')}`.trimEnd() + '\n');

if (name === 'ps') {
  console.log(process.env.BD_PS ?? '100 /Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay');
  process.exit(0);
}
if (name === 'aerospace') {
  if (args[0] === 'list-monitors') console.log(process.env.STUB_MONITORS ?? '1');
  process.exit(0);
}

const file = join(dir, 'bd.json');
const initial = {
  displays: [
    {
      name: '32G1WG4',
      deviceType: 'Display',
      tagID: '2',
      UUID: 'AAAA-1',
      displayID: '2',
      props: { resolution: '1920x1080', hiDPI: 'off', refreshRate: '144Hz', brightness: '1.0', mirror: 'off', main: 'true', connected: 'on' },
      modes: ['0 - 1920x1080 144Hz 10bpc', '1 - 1920x1080 HiDPI 144Hz 10bpc', '2 - 1280x720 60Hz 10bpc', '3 - 2560x1440 60Hz 8bpc'],
    },
  ],
};
const db = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : initial;
const save = () => writeFileSync(file, JSON.stringify(db));
const fail = (msg = 'Failed.') => {
  console.log(msg);
  process.exit(1);
};

const [op, ...rest] = args;
const kv = {};
for (const a of rest) {
  const m = /^--([A-Za-z0-9]+)(?:=(.*))?$/.exec(a);
  if (m) kv[m[1]] = m[2] ?? true;
}
const SELECTORS = ['name', 'tagID', 'UUID', 'type'];
const features = Object.keys(kv).filter((k) => !SELECTORS.includes(k) && k !== 'targetName');
const find = () => db.displays.find((d) => d.name === kv.name);

if (process.env.BD_FAIL && (op === 'set' || op === 'create') && Object.keys(kv).includes(process.env.BD_FAIL)) fail();

if (op === 'get') {
  if (kv.identifiers) {
    const recs = db.displays.map((d) => ({ UUID: d.UUID, deviceType: d.deviceType, displayID: d.displayID, name: d.name, tagID: d.tagID }));
    console.log(recs.map((r) => JSON.stringify(r, null, 2)).join(',\n'));
  } else if (kv.proAvailable) console.log(process.env.BD_PRO === 'off' ? 'off' : 'on');
  else {
    const d = find();
    if (!d) fail();
    if (kv.displayModeList) console.log((d.modes ?? []).join('\n'));
    else {
      const f = features[0];
      const v = d.props[f];
      if (v === undefined) fail();
      console.log(v);
    }
  }
} else if (op === 'set') {
  const d = find();
  if (!d) fail();
  for (const f of features) d.props[f] = f === 'brightness' && String(kv[f]).endsWith('%') ? String(parseFloat(kv[f]) / 100) : kv[f];
  if (kv.mirror === 'on') d.props.mirrorTarget = kv.targetName;
  if (kv.mirror === 'off') delete d.props.mirrorTarget;
  save();
} else if (op === 'create') {
  if (kv.type !== 'VirtualScreen') fail();
  const n = kv.virtualScreenName ?? `virtual-${db.displays.length}`;
  db.displays.push({
    name: n,
    deviceType: 'VirtualScreen',
    tagID: String(10 + db.displays.length),
    UUID: `V-${n}`,
    displayID: String(20 + db.displays.length),
    props: { resolution: '1920x1080', hiDPI: kv.virtualScreenHiDPI ?? 'off', mirror: 'off', main: 'false', connected: 'on' },
    modes: (kv.resolutionList ?? '').split(',').filter(Boolean).map((r, i) => `${i} - ${r} HiDPI 60Hz`),
  });
  save();
} else if (op === 'discard') {
  // The real CLI discards EVERYTHING discardable when no identifier is given. Mirror that, so tests catch it.
  db.displays = db.displays.filter((d) => !(d.deviceType === 'VirtualScreen' && (!kv.name || d.name === kv.name)));
  save();
} else fail();
