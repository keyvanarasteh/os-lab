#!/usr/bin/env node
// Generic stub for external commands. Usage (via wrapper): stub.mjs <name> [args...]
// Logs every call to $STUB_LOG. `defaults` keeps a tiny JSON store in $STUB_DIR/defaults.json.
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [name, ...args] = process.argv.slice(2);
const dir = process.env.STUB_DIR;
appendFileSync(process.env.STUB_LOG, `${name} ${args.join(' ')}`.trimEnd() + '\n');

if (name === 'defaults') {
  const file = join(dir, 'defaults.json');
  const db = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
  const [verb, domain, key, type, value] = args;
  const k = `${domain} ${key}`;
  if (verb === 'read') {
    if (!(k in db)) {
      console.error(`The domain/default pair of (${domain}, ${key}) does not exist`);
      process.exit(1);
    }
    console.log(db[k]);
  } else if (verb === 'write') {
    // bools are stored the way `defaults read` prints them
    db[k] = type === '-bool' ? (value === 'true' ? '1' : '0') : value;
    writeFileSync(file, JSON.stringify(db));
  } else if (verb === 'delete') {
    delete db[k];
    writeFileSync(file, JSON.stringify(db));
  }
} else if ((name === 'open' || name === 'osascript') && !process.env.STUB_NO_WINDOWS) {
  // launching an app "creates" a window with a fresh id
  const file = join(dir, 'windows.json');
  const ids = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : [100];
  ids.push(Math.max(...ids) + 1);
  writeFileSync(file, JSON.stringify(ids));
} else if (name === 'aerospace') {
  const wfile = join(dir, 'windows.json');
  if (args[0] === 'list-windows' && args.includes('--all') && args.includes('--format') && args.includes('%{window-id}')) {
    console.log((existsSync(wfile) ? JSON.parse(readFileSync(wfile, 'utf8')) : [100]).join('\n'));
  } else if (args[0] === 'list-windows' && args.includes('--count')) console.log(process.env.STUB_WINCOUNT ?? '3');
  else if (args[0] === 'list-workspaces' && args.includes('--focused')) console.log(process.env.STUB_FOCUSED ?? '1-proj-a');
  else if (args[0] === 'list-workspaces') console.log('0-home\n1-proj-a\n2-proj-b\n3-proj-c\nagents\ncomms');
  else if (args[0] === 'list-windows') console.log('1 | Cursor | main');
  else if (args[0] === 'list-apps') console.log('100 | com.example.app | Example');
}
