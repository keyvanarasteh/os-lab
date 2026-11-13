"""Relocating a cache to another volume behind a symlink (CLN-27).

Ports the *behaviour* of ``cleanup_ref.relocation`` (see ``PARITY.md``) without
its bugs (``README.md``, "Do not port"):

* **Ordered and verified.** A move is ``copy → verify → rename aside → symlink →
  verify link → remove aside``. At every point the original, a verified copy, or
  both exist; a failed step stops the job with a reason instead of continuing.
* **No elevated fallback.** A permission error fails the step. Nothing here
  assembles a shell command, and nothing retries as root.
* **Interrupted runs are detected and can be resumed.** ``.oslab-moving`` and
  ``.oslab-restoring`` mark a step that did not finish. A resume plan either
  completes the link or rolls the set-aside original back; it never guesses.
* **Destination volumes are explicit.** The console derives the store path under
  a volume reported by ``volumes.report`` (CLN-28) and passes that mount point as
  ``destination_root``; the engine re-checks the copy pair with the CLN-12 policy.

Nothing here runs unless a console job starts after the user confirms the plan.
Planning is read-only (``lstat`` / ``readlink`` / a fingerprint walk); symlinks
are counted, never followed.
"""
from __future__ import annotations

import enum
import os
import shutil
import stat
import time
import uuid
from dataclasses import dataclass

from . import safety
from .clean import retry
from .paths import platform_id

ASIDE_SUFFIX = ".oslab-moving"
RESTORE_SUFFIX = ".oslab-restoring"
#: Extra free space required on the destination beyond the measured size.
DEFAULT_PAD_BYTES = 256 * 1024 * 1024
PLAN_TTL = 600.0
ACTIONS = ("move", "restore", "relink", "resume")


class FolderStatus(enum.Enum):
    LOCAL_ONLY = "local_only"        # real folder at home, nothing on the store
    LINKED_OK = "linked_ok"          # home is a symlink to the store copy, which exists
    MISSING_LINK = "missing_link"    # store copy exists, home path absent
    BROKEN_LINK = "broken_link"      # home is a symlink whose target is missing
    WRONG_TARGET = "wrong_target"    # home is a symlink to somewhere else that exists
    CONFLICT = "conflict"            # real folder at home AND a store copy
    MISSING = "missing"              # neither side exists


class RelocationError(ValueError):
    """The plan or a step was refused. ``code`` is stable; the message is shown."""

    def __init__(self, message, code="relocation-invalid"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Step:
    #: copy | verify_copy | rename | symlink | verify_link | remove_tree | remove_link
    op: str
    src: str
    dst: str = ""

    def to_dict(self):
        return {"op": self.op, "src": self.src, "dst": self.dst}


@dataclass
class Plan:
    """A confirmable relocation plan. Single-use and short-lived in the console."""

    id: str
    action: str
    home_path: str
    store_path: str
    volume_id: str
    platform: str
    status: str
    interrupted: str | None
    size_bytes: int
    free_bytes: int
    pad_bytes: int
    steps: list
    created_at: float
    expires_at: float

    def to_dict(self):
        return {
            "planId": self.id,
            "action": self.action,
            "status": self.status,
            "interrupted": self.interrupted,
            "homePath": self.home_path,
            "storePath": self.store_path,
            "volumeId": self.volume_id,
            "platform": self.platform,
            "sizeBytes": self.size_bytes,
            "freeBytes": self.free_bytes,
            "padBytes": self.pad_bytes,
            "expiresAt": self.expires_at,
            "ttlSeconds": PLAN_TTL,
            "steps": [step.to_dict() for step in self.steps],
        }


def _lexists(path):
    return os.path.lexists(path)


def _is_link(path):
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _link_target(link):
    target = os.readlink(link)
    if not os.path.isabs(target):
        target = os.path.join(os.path.dirname(link), target)
    return os.path.normpath(target)


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def classify(home_path, store_path):
    """The link state of ``home_path`` relative to ``store_path``; seven states."""
    store_exists = _lexists(store_path) and not _is_link(store_path)
    if _is_link(home_path):
        try:
            target = _link_target(home_path)
        except OSError:
            return FolderStatus.BROKEN_LINK
        if not os.path.exists(target):
            return FolderStatus.BROKEN_LINK
        if _same(target, store_path):
            return FolderStatus.LINKED_OK
        return FolderStatus.WRONG_TARGET
    if _lexists(home_path) and store_exists:
        return FolderStatus.CONFLICT
    if store_exists:
        return FolderStatus.MISSING_LINK
    if _lexists(home_path):
        return FolderStatus.LOCAL_ONLY
    return FolderStatus.MISSING


def interrupted_kind(home_path, store_path):
    """``"move"`` / ``"restore"`` / ``None`` for an unfinished earlier run."""
    moving = _lexists(home_path + ASIDE_SUFFIX) and not _is_link(home_path + ASIDE_SUFFIX)
    restoring = _lexists(home_path + RESTORE_SUFFIX) and not _is_link(home_path + RESTORE_SUFFIX)
    if moving and restoring:
        return "both"
    if moving:
        return "move"
    if restoring:
        return "restore"
    return None


def tree_fingerprint(root):
    """``(entry_count, regular_bytes)`` under ``root``; symlinks counted, never followed."""
    files = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames + [
            item for item in dirnames if _is_link(os.path.join(dirpath, item))
        ]:
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            files += 1
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return files, total


def measure(path):
    """``(entry_count, regular_bytes)`` for a file, folder or missing path."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0, 0
    if stat.S_ISREG(st.st_mode):
        return 1, st.st_size
    if stat.S_ISDIR(st.st_mode):
        return tree_fingerprint(path)
    return 1, 0  # a symlink or special file has no bytes to copy


def _check_pair(home, store, *, destination_root=None):
    """Shared path policy for every plan; a catalog path is still checked."""
    for raw in (home, store):
        try:
            safety.canonical(raw)
        except safety.PathPolicyError as exc:
            raise RelocationError(str(exc), exc.code) from exc
    if destination_root is not None:
        try:
            safety.validate_copy(home, store, destination_root)
        except safety.PathPolicyError as exc:
            raise RelocationError(str(exc), exc.code) from exc
    def nested(a, b):
        a, b = os.path.normcase(os.path.normpath(a)), os.path.normcase(os.path.normpath(b))
        try:
            return os.path.commonpath([a, b]) in (a, b)
        except ValueError:
            return False

    if nested(store, home):
        raise RelocationError("The cache and its store must not contain each other.", "nested")


def plan_move(
    home_path,
    store_path,
    *,
    size_bytes,
    free_bytes,
    pad_bytes=DEFAULT_PAD_BYTES,
    destination_root=None,
):
    """Steps to move a local folder/file to the store and leave a symlink behind."""
    status = classify(home_path, store_path)
    interrupted = interrupted_kind(home_path, store_path)
    if interrupted is not None:
        raise RelocationError(
            "A previous run was interrupted; resume it instead.", "interrupted"
        )
    if status is not FolderStatus.LOCAL_ONLY:
        raise RelocationError(
            "Cannot move: the state is {0}, expected local_only.".format(status.value),
            "state",
        )
    _check_pair(home_path, store_path, destination_root=destination_root)
    if free_bytes < size_bytes + pad_bytes:
        raise RelocationError(
            "Not enough free space on the destination (need {0} bytes, have {1}).".format(
                size_bytes + pad_bytes, free_bytes
            ),
            "no-space",
        )
    aside = home_path + ASIDE_SUFFIX
    return [
        Step("copy", home_path, store_path),
        Step("verify_copy", home_path, store_path),
        Step("rename", home_path, aside),
        Step("symlink", home_path, store_path),
        Step("verify_link", home_path, store_path),
        Step("remove_tree", aside),
    ]


def plan_restore(
    home_path,
    store_path,
    *,
    size_bytes=None,
    free_bytes=None,
    pad_bytes=DEFAULT_PAD_BYTES,
    keep_store_copy=True,
):
    """Steps to bring a relocated cache back to ``home_path``; the store is kept."""
    status = classify(home_path, store_path)
    interrupted = interrupted_kind(home_path, store_path)
    if interrupted is not None:
        raise RelocationError(
            "A previous run was interrupted; resume it instead.", "interrupted"
        )
    if status not in (
        FolderStatus.LINKED_OK,
        FolderStatus.MISSING_LINK,
        FolderStatus.BROKEN_LINK,
    ):
        raise RelocationError("Cannot restore: the state is {0}.".format(status.value), "state")
    if status is FolderStatus.BROKEN_LINK:
        raise RelocationError(
            "Cannot restore: the store copy is missing. Remove the broken link instead.",
            "missing-store",
        )
    if size_bytes is not None and free_bytes is not None and free_bytes < size_bytes + pad_bytes:
        raise RelocationError(
            "Not enough free space at home (need {0} bytes, have {1}).".format(
                size_bytes + pad_bytes, free_bytes
            ),
            "no-space",
        )
    staging = home_path + RESTORE_SUFFIX
    steps = [Step("copy", store_path, staging), Step("verify_copy", store_path, staging)]
    if status is FolderStatus.LINKED_OK:
        steps.append(Step("remove_link", home_path))
    steps.append(Step("rename", staging, home_path))
    if not keep_store_copy:
        steps.append(Step("remove_tree", store_path))
    return steps


def plan_relink(home_path, store_path):
    """Repair a missing or wrong link; a real folder is never removed."""
    status = classify(home_path, store_path)
    interrupted = interrupted_kind(home_path, store_path)
    if interrupted is not None:
        raise RelocationError(
            "A previous run was interrupted; resume it instead.", "interrupted"
        )
    if status is FolderStatus.MISSING_LINK:
        return [Step("symlink", home_path, store_path), Step("verify_link", home_path, store_path)]
    if status in (FolderStatus.WRONG_TARGET, FolderStatus.BROKEN_LINK) and os.path.exists(store_path):
        return [
            Step("remove_link", home_path),
            Step("symlink", home_path, store_path),
            Step("verify_link", home_path, store_path),
        ]
    raise RelocationError("Cannot relink: the state is {0}.".format(status.value), "state")


def _resume_move_steps(home_path, store_path):
    """Finish or roll back an interrupted move, never discarding unverified data."""
    aside = home_path + ASIDE_SUFFIX
    if not _lexists(aside):
        raise RelocationError("There is no interrupted move to resume.", "no-interrupted")
    if _is_link(aside):
        raise RelocationError("The set-aside original is a symlink.", "bad-aside")
    if _is_link(home_path):
        try:
            target = _link_target(home_path)
        except OSError:
            target = ""
        if os.path.exists(store_path) and _same(target, store_path):
            return [Step("verify_link", home_path, store_path), Step("remove_tree", aside)]
        if _lexists(store_path) and not _is_link(store_path):
            return [
                Step("remove_link", home_path),
                Step("symlink", home_path, store_path),
                Step("verify_link", home_path, store_path),
                Step("remove_tree", aside),
            ]
        raise RelocationError(
            "Cannot resume: the home path is a link but the store copy is missing.", "missing-store"
        )
    if _lexists(home_path):
        raise RelocationError(
            "Cannot resume: both the home path and the set-aside original exist.", "conflict"
        )
    if _lexists(store_path) and not _is_link(store_path):
        if measure(store_path) != measure(aside):
            raise RelocationError(
                "Cannot resume: the store copy does not match the set-aside original.",
                "unverified-store",
            )
        return [
            Step("symlink", home_path, store_path),
            Step("verify_link", home_path, store_path),
            Step("remove_tree", aside),
        ]
    # No copy survived: the set-aside original is the only data. Put it back.
    return [Step("rename", aside, home_path)]


def _resume_restore_steps(home_path, store_path):
    staging = home_path + RESTORE_SUFFIX
    if not _lexists(staging):
        raise RelocationError("There is no interrupted restore to resume.", "no-interrupted")
    if _is_link(staging):
        raise RelocationError("The restore staging path is a symlink.", "bad-staging")
    if measure(staging) != measure(store_path):
        raise RelocationError(
            "Cannot resume: the store copy does not match the staging copy.", "unverified-store"
        )
    steps = []
    if _is_link(home_path):
        steps.append(Step("remove_link", home_path))
    elif _lexists(home_path):
        raise RelocationError(
            "Cannot resume: both the home path and the restore staging exist.", "conflict"
        )
    steps.append(Step("rename", staging, home_path))
    return steps


def plan_resume(home_path, store_path):
    """Steps to finish (or safely roll back) an interrupted move/restore."""
    kind = interrupted_kind(home_path, store_path)
    if kind == "both":
        raise RelocationError(
            "Both .oslab-moving and .oslab-restoring exist; choose one manually.",
            "conflict",
        )
    if kind == "move":
        return _resume_move_steps(home_path, store_path)
    if kind == "restore":
        return _resume_restore_steps(home_path, store_path)
    raise RelocationError("There is no interrupted run to resume.", "no-interrupted")


def build_plan(
    home_path,
    store_path,
    action,
    *,
    volume_id,
    destination_root,
    pad_bytes=DEFAULT_PAD_BYTES,
    free_bytes=None,
    disk_usage=shutil.disk_usage,
    clock=time.time,
    platform=None,
):
    """Validate a typed request and return a read-only :class:`Plan`.

    The console has already checked the entry id, catalog path, volume and the
    CLN-12 owner/running-app lock; this function owns the file-level ordering.
    """
    if action not in ACTIONS:
        raise RelocationError(
            "action must be one of {0}".format(", ".join(ACTIONS)), "bad-action"
        )
    home = safety.canonical(home_path)
    store = safety.canonical(store_path)
    _check_pair(home, store)
    status = classify(home, store)
    interrupted = interrupted_kind(home, store)

    size_bytes = 0
    if action == "move":
        size_bytes = measure(home)[1]
        if free_bytes is None:
            free_bytes = disk_usage(destination_root).free
        steps = plan_move(
            home, store, size_bytes=size_bytes, free_bytes=free_bytes,
            pad_bytes=pad_bytes, destination_root=destination_root,
        )
    elif action == "restore":
        size_bytes = measure(store)[1]
        if free_bytes is None:
            free_bytes = disk_usage(destination_root).free
        steps = plan_restore(
            home, store, size_bytes=size_bytes, free_bytes=free_bytes, pad_bytes=pad_bytes
        )
    elif action == "relink":
        if free_bytes is None:
            free_bytes = disk_usage(destination_root).free
        steps = plan_relink(home, store)
    else:
        if free_bytes is None:
            free_bytes = disk_usage(destination_root).free
        steps = plan_resume(home, store)

    created = clock()
    return Plan(
        id=uuid.uuid4().hex[:12],
        action=action,
        home_path=home,
        store_path=store,
        volume_id=volume_id,
        platform=platform or platform_id(),
        status=status.value,
        interrupted=interrupted,
        size_bytes=size_bytes,
        free_bytes=free_bytes,
        pad_bytes=pad_bytes,
        steps=steps,
        created_at=created,
        expires_at=created + PLAN_TTL,
    )


# ── Execution ───────────────────────────────────────────────────────────────


def _cancelled(cancel):
    return cancel is not None and cancel.is_set()


def _copy_entry(src, dst, *, copy_tree=shutil.copytree, copy_file=shutil.copy2,
                symlink=os.symlink, makedirs=os.makedirs):
    if _lexists(dst):
        raise RelocationError("The destination already exists: {0}".format(dst), "destination-exists")
    parent = os.path.dirname(dst)
    if parent:
        makedirs(parent, exist_ok=True)
    st = os.lstat(src)
    if stat.S_ISLNK(st.st_mode):
        symlink(os.readlink(src), dst)
    elif stat.S_ISREG(st.st_mode):
        copy_file(src, dst)
    elif stat.S_ISDIR(st.st_mode):
        copy_tree(src, dst, symlinks=True)
    else:
        raise RelocationError("Not a regular file or folder: {0}".format(src), "not-copyable")


def _verify_copy(src, dst):
    if not _lexists(src) or not _lexists(dst):
        raise RelocationError("The copy is missing on one side.", "copy-missing")
    if measure(src) != measure(dst):
        raise RelocationError(
            "The copy does not match the original (count or bytes differ).", "copy-mismatch"
        )


def _verify_link(home, store):
    if not _is_link(home):
        raise RelocationError("The home path is not a symlink.", "link-missing")
    if not os.path.exists(store):
        raise RelocationError("The store copy is missing.", "missing-store")
    if not _same(_link_target(home), store):
        raise RelocationError("The symlink does not point at the store.", "link-wrong")


def _remove_tree(root, *, unlink=os.unlink, rmdir=os.rmdir, sleep=time.sleep):
    try:
        root_mode = os.lstat(root).st_mode
    except OSError as exc:
        return [(root, exc)]
    if not stat.S_ISDIR(root_mode):
        try:
            retry(lambda: unlink(root), sleep=sleep)
            return []
        except OSError as exc:
            return [(root, exc)]
    errors = []
    directories = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                listing = list(iterator)
        except OSError as exc:
            errors.append((current, exc))
            continue
        directories.append(current)
        for child in listing:
            try:
                mode = child.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                errors.append((child.path, exc))
                continue
            if stat.S_ISDIR(mode):
                stack.append(child.path)
                continue
            try:
                retry(lambda path=child.path: unlink(path), sleep=sleep)
            except OSError as exc:
                errors.append((child.path, exc))
    for directory in reversed(directories):
        try:
            retry(lambda path=directory: rmdir(path), sleep=sleep)
        except OSError as exc:
            errors.append((directory, exc))
    return errors


def _run_step(step, *, rename, unlink, rmdir, symlink, makedirs, sleep, copy_tree,
              copy_file):
    if step.op == "copy":
        _copy_entry(step.src, step.dst, copy_tree=copy_tree, copy_file=copy_file,
                    symlink=symlink, makedirs=makedirs)
    elif step.op == "verify_copy":
        _verify_copy(step.src, step.dst)
    elif step.op == "rename":
        parent = os.path.dirname(step.dst)
        if parent:
            makedirs(parent, exist_ok=True)
        retry(lambda: rename(step.src, step.dst), sleep=sleep)
    elif step.op == "symlink":
        parent = os.path.dirname(step.src)
        if parent:
            makedirs(parent, exist_ok=True)
        if _lexists(step.src):
            raise RelocationError("The home path already exists.", "destination-exists")
        retry(lambda: symlink(step.dst, step.src), sleep=sleep)
    elif step.op == "verify_link":
        _verify_link(step.src, step.dst)
    elif step.op == "remove_tree":
        errors = _remove_tree(step.src, unlink=unlink, rmdir=rmdir, sleep=sleep)
        if errors:
            location, exc = errors[0]
            raise RelocationError(
                "Could not remove the set-aside original: {0} ({1} entries failed).".format(
                    location, len(errors)
                ),
                "remove-failed",
            )
    elif step.op == "remove_link":
        retry(lambda: unlink(step.src), sleep=sleep)
    else:
        raise RelocationError("Unknown relocation step {0}.".format(step.op), "bad-step")


def _preserved(plan):
    """What still holds the data after a failure: original, aside, store or link."""
    home, store = plan.home_path, plan.store_path
    aside = home + ASIDE_SUFFIX
    staging = home + RESTORE_SUFFIX
    if _lexists(home) and not _is_link(home):
        return "original"
    for path, name in ((aside, "aside"), (staging, "staging")):
        if _lexists(path):
            return name
    if _is_link(home) and os.path.exists(store):
        return "store"
    if os.path.exists(store):
        return "store"
    return "none"


def execute(
    plan,
    *,
    cancel=None,
    progress_callback=None,
    rename=os.rename,
    unlink=os.unlink,
    rmdir=os.rmdir,
    symlink=os.symlink,
    makedirs=os.makedirs,
    copy_tree=shutil.copytree,
    copy_file=shutil.copy2,
    sleep=time.sleep,
    clock=time.time,
):
    """Run a confirmed plan; stop at the first failure and report every step."""
    started = clock()
    total = len(plan.steps)
    progress = {
        "phase": "running",
        "stepsDone": 0,
        "stepsTotal": total,
        "currentStep": "",
    }

    def emit():
        if progress_callback is not None:
            progress_callback(dict(progress))

    emit()
    steps = []
    failed = False
    cancelled = False
    for index, step in enumerate(plan.steps):
        if _cancelled(cancel):
            cancelled = True
        if cancelled:
            steps.append({"op": step.op, "src": step.src, "dst": step.dst,
                          "state": "skipped", "error": "The run was cancelled."})
            continue
        progress["currentStep"] = step.op
        emit()
        try:
            _run_step(
                step, rename=rename, unlink=unlink, rmdir=rmdir, symlink=symlink,
                makedirs=makedirs, sleep=sleep, copy_tree=copy_tree, copy_file=copy_file,
            )
        except (OSError, RelocationError) as exc:
            failed = True
            steps.append({"op": step.op, "src": step.src, "dst": step.dst,
                          "state": "failed",
                          "error": "{0}: {1}".format(type(exc).__name__, exc)})
            for rest in plan.steps[index + 1:]:
                steps.append({"op": rest.op, "src": rest.src, "dst": rest.dst,
                              "state": "skipped", "error": "A previous step failed."})
            break
        steps.append({"op": step.op, "src": step.src, "dst": step.dst,
                      "state": "done", "error": None})
        progress["stepsDone"] += 1
        emit()

    finished = clock()
    state = "cancelled" if cancelled else "failed" if failed else "done"
    progress["phase"] = state
    errors = [row["error"] for row in steps if row["state"] == "failed"]
    return {
        "planId": plan.id,
        "action": plan.action,
        "homePath": plan.home_path,
        "storePath": plan.store_path,
        "volumeId": plan.volume_id,
        "platform": plan.platform,
        "state": state,
        "cancelled": cancelled,
        "interrupted": interrupted_kind(plan.home_path, plan.store_path),
        "preserved": _preserved(plan),
        "linkStatus": classify(plan.home_path, plan.store_path).value,
        "steps": steps,
        "progress": progress,
        "startedAt": started,
        "finishedAt": finished,
        "durationMs": int(round((finished - started) * 1000)),
        "error": errors[0] if errors else None,
    }
