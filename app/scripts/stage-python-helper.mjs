#!/usr/bin/env node
// Stage pinned uv executables for app-managed Python installation. Only release builds call this.
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const VERSION = "0.13.7";
const ASSETS = {
  "aarch64-apple-darwin": "81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731",
  "x86_64-apple-darwin": "20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7",
  "x86_64-pc-windows-msvc": "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021",
  "x86_64-unknown-linux-gnu": "c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83",
  "aarch64-unknown-linux-gnu": "71279f8d3c67241e807b9d8db872d1bf541579fb9f08b7d1eb1682196d1e57dc",
};
const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "..", "src-tauri", "resources", "tools");

export function targets(platform = process.platform, arch = process.arch) {
  if (platform === "darwin") return ["aarch64-apple-darwin", "x86_64-apple-darwin"]; // universal DMG
  if (platform === "win32" && arch === "x64") return ["x86_64-pc-windows-msvc"];
  if (platform === "linux" && arch === "x64") return ["x86_64-unknown-linux-gnu"];
  if (platform === "linux" && arch === "arm64") return ["aarch64-unknown-linux-gnu"];
  throw new Error(`No app-managed Python helper for ${platform}/${arch}`);
}

function findBinary(dir, name) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      const found = findBinary(path, name);
      if (found) return found;
    } else if (entry.isFile() && entry.name === name) {
      return path;
    }
  }
  return null;
}

async function stage(target) {
  const ext = target.includes("windows") ? "zip" : "tar.gz";
  const asset = `uv-${target}.${ext}`;
  const url = `https://github.com/astral-sh/uv/releases/download/${VERSION}/${asset}`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${asset}: HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (digest !== ASSETS[target]) throw new Error(`${asset}: SHA-256 mismatch`);
  const temp = mkdtempSync(join(tmpdir(), "os-lab-uv-"));
  try {
    const archive = join(temp, asset);
    writeFileSync(archive, bytes);
    execFileSync("tar", ["-xf", archive, "-C", temp]);
    const exe = target.includes("windows") ? "uv.exe" : "uv";
    const binary = findBinary(temp, exe);
    if (!binary) throw new Error(`${asset}: ${exe} missing from archive`);
    const dest = join(out, `uv-${target}${target.includes("windows") ? ".exe" : ""}`);
    copyFileSync(binary, dest);
    if (!target.includes("windows")) chmodSync(dest, 0o755);
    if (target.includes("apple-darwin") && process.env.APPLE_SIGNING_IDENTITY) {
      execFileSync("codesign", ["--force", "--options", "runtime", "--timestamp", "--sign", process.env.APPLE_SIGNING_IDENTITY, dest]);
    }
    console.log(`staged ${dest}`);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
}

async function main() {
  if (process.platform === "darwin" && process.env.APPLE_CERTIFICATE && !process.env.APPLE_SIGNING_IDENTITY) {
    throw new Error("Import the Developer ID certificate into the keychain and set APPLE_SIGNING_IDENTITY to sign bundled Python helpers");
  }
  mkdirSync(out, { recursive: true });
  for (const entry of readdirSync(out)) {
    if (entry.startsWith("uv-")) rmSync(join(out, entry), { force: true });
  }
  for (const target of targets()) await stage(target);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => { console.error(error); process.exitCode = 1; });
}
