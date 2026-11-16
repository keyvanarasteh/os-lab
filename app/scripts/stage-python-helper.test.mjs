import assert from "node:assert/strict";
import { test } from "node:test";
import { targets } from "./stage-python-helper.mjs";

test("release platforms stage a helper for every supported architecture", () => {
  assert.deepEqual(targets("darwin", "arm64"), ["aarch64-apple-darwin", "x86_64-apple-darwin"]);
  assert.deepEqual(targets("win32", "x64"), ["x86_64-pc-windows-msvc"]);
  assert.deepEqual(targets("linux", "x64"), ["x86_64-unknown-linux-gnu"]);
  assert.deepEqual(targets("linux", "arm64"), ["aarch64-unknown-linux-gnu"]);
  assert.throws(() => targets("win32", "arm64"));
});
