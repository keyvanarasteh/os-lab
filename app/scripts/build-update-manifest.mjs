#!/usr/bin/env node
// Assemble the Tauri updater feed only after every supported host has a signed artifact.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [version, directory, output] = process.argv.slice(2);
if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(version || "") || !directory || !output) {
  throw new Error("usage: node build-update-manifest.mjs <version> <release-assets-dir> <output-json>");
}

const base = `https://github.com/keyvanarasteh/os-lab/releases/download/app-v${version}`;
const assets = {
  "darwin-x86_64": `os-lab_${version}_macos_universal.app.tar.gz`,
  "darwin-aarch64": `os-lab_${version}_macos_universal.app.tar.gz`,
  "windows-x86_64": `os-lab_${version}_windows_x64-setup.exe`,
  "linux-x86_64": `os-lab_${version}_linux_amd64.AppImage`,
  "linux-aarch64": `os-lab_${version}_linux_arm64.AppImage`,
};

const platforms = {};
for (const [platform, name] of Object.entries(assets)) {
  const bytes = readFileSync(join(directory, name));
  const checksum = readFileSync(join(directory, `${name}.sha256`), "utf8").trim();
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (checksum !== `${actual}  ${name}`) throw new Error(`${name}: SHA-256 mismatch`);
  const signature = readFileSync(join(directory, `${name}.sig`), "utf8").trim();
  if (!signature) throw new Error(`${name}: empty updater signature`);
  platforms[platform] = { url: `${base}/${name}`, signature };
}

writeFileSync(output, `${JSON.stringify({ version, platforms }, null, 2)}\n`);
console.log(`Updater manifest ready for ${version}: ${Object.keys(platforms).join(", ")}`);
