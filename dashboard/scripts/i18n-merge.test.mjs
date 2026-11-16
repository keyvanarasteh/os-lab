// Tests for the locale JSON merge driver (plan item C), including a real git rebase.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { mergeDictionaries } from "../../scripts/lib/i18n-merge-driver.mjs";

const driver = resolve(import.meta.dirname, "../../scripts/lib/i18n-merge-driver.mjs");

test("keys added at the end on both sides are both kept", () => {
  const { result, conflicts } = mergeDictionaries({ a: "1" }, { a: "1", b: "2" }, { a: "1", c: "3" });
  assert.deepEqual(conflicts, []);
  assert.deepEqual(Object.keys(result), ["a", "b", "c"]);
});

test("one-sided edits and deletions win; the same addition is kept once", () => {
  const { result, conflicts } = mergeDictionaries({ a: "1", d: "x" }, { a: "1b", s: "same" }, { a: "1", d: "x", s: "same" });
  assert.deepEqual(conflicts, []);
  assert.deepEqual(result, { a: "1b", s: "same" });
});

test("different texts for one key are a conflict", () => {
  assert.deepEqual(mergeDictionaries({}, { k: "one" }, { k: "two" }).conflicts, ["k"]);
});

test("a rebase where both branches append keys has no conflict", () => {
  const dir = mkdtempSync(join(tmpdir(), "i18n-merge-"));
  const git = (...args) => execFileSync("git", args, { cwd: dir, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  const write = (object) => writeFileSync(join(dir, "tr.json"), `${JSON.stringify(object, null, 2)}\n`);
  try {
    git("init", "-q", "-b", "master");
    git("config", "user.email", "test@example.invalid");
    git("config", "user.name", "test");
    git("config", "merge.oslab-i18n.driver", `node ${driver} %O %A %B %P`);
    writeFileSync(join(dir, ".gitattributes"), "*.json merge=oslab-i18n\n");
    write({ Home: "Ana sayfa" });
    git("add", "."); git("commit", "-qm", "base");
    git("switch", "-qc", "feature");
    write({ Home: "Ana sayfa", Feedback: "Geri bildirim" });
    git("commit", "-qam", "feature key");
    git("switch", "-q", "master");
    write({ Home: "Ana sayfa", Notifications: "Bildirimler" });
    git("commit", "-qam", "master key");
    git("switch", "-q", "feature");
    git("rebase", "-q", "master");
    assert.deepEqual(JSON.parse(readFileSync(join(dir, "tr.json"), "utf8")), {
      Home: "Ana sayfa", Notifications: "Bildirimler", Feedback: "Geri bildirim"
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
