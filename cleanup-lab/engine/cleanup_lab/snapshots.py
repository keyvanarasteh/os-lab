"""CLN-31: versioned disk-usage snapshots — interchange export, import, diff.

A snapshot is an explorer size tree frozen into a small, documented exchange
format so it can be stored, diffed over time and read by other tools. The
shape is the classic ncdu-1.x interchange document:

    [1, 1, {"progname": ..., "progver": ..., "timestamp": ...},
     <root info object>, [<root items>]]

a directory is ``[ {info}, [children…] ]``, a plain file is ``{info}``, and an
info object carries ``name`` and ``asize`` (apparent bytes) plus the optional
``dsize`` (on-disk bytes, omitted when unknown), ``ino`` and ``dev`` (the
latter only when it differs from the parent's), ``read_error: true``,
``notreg: true`` and ``excluded: "<reason>"``. This writer announces version
``0.4.0``; the reader accepts major version 1 with minor version 1 or 2, so
documents written by the classic tool round-trip through this module too.

The explorer's honesty rules survive the interchange:

* a node whose ``unreadable`` count is above zero is exported with
  ``read_error: true`` — the format records that something could not be
  read, never the count;
* a truncated node is exported as ``excluded: "budget"`` and restored as
  ``truncated`` on import;
* an entry without ``dsize`` is imported with ``sizeOnDiskBytes: None`` —
  unknown stays unknown instead of becoming a guess.

``import_is_read_only`` is a documented property of this module: nothing in
it writes anywhere but the exact ``out_path`` handed to
:func:`export_snapshot`. Reading and diffing open only the snapshot files
they were given — no state folder, no cache, no side effects.

Exports follow the settings store's atomic-write discipline: a ``0600``
temporary file that is fsynced and ``os.replace``d into place, a refused
symlink destination and a private (``0700``) parent folder on POSIX. Imports
are streaming with a node budget, so a huge or hostile document is refused
with an honest reason instead of being loaded forever.
"""
from __future__ import annotations

import json
import os
import stat
import time

#: The writer identity recorded in every export header.
PROGNAME = "os-lab-cleanup"
#: The writer's version string, recorded in every export header.
WRITER_VERSION = "0.4.0"
#: The interchange versions this reader accepts: major 1, minor 1 or 2.
SUPPORTED_MAJOR = 1
SUPPORTED_MINORS = (1, 2)
#: The default node budget for :func:`read_snapshot`.
DEFAULT_MAX_NODES = 500000

_MAX_DEPTH = 256
_MAX_VALUE_CHARS = 262144
_CHUNK = 65536
_WHITESPACE = " \t\r\n"

#: The info-object keys this reader understands; everything else is skipped.
_INFO_KEYS = frozenset({"name", "asize", "dsize", "ino", "dev", "read_error", "notreg", "excluded"})
#: The header keys this reader understands; everything else is skipped.
_HEADER_KEYS = frozenset({"progname", "progver", "timestamp"})


class SnapshotError(RuntimeError):
    """A snapshot cannot be exported, read or diffed; the message is the honest reason."""


# ---------------------------------------------------------------- integrity


def _is_count(value):
    """A real non-negative integer (bools are not counts)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _opt_count(value):
    """The count when the value is a usable non-negative integer, else None."""
    return value if _is_count(value) else None


def _silent_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _fsync_dir(folder):
    try:
        dir_fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


# ------------------------------------------------------------- the reader


class _Stream:
    """A buffered, forward-only reader over a snapshot document.

    Values are decoded one at a time with :meth:`json.JSONDecoder.raw_decode`
    while the framing (``[``, ``,`` …) is checked by hand, so the parse never
    holds more than one value in memory and the node budget can cut a hostile
    document off mid-stream.
    """

    def __init__(self, handle):
        self._handle = handle
        self._decoder = json.JSONDecoder()
        self._buf = ""
        self._pos = 0
        self._eof = False

    def _fill(self):
        if self._eof:
            return False
        if self._pos > _CHUNK:  # drop the consumed prefix, keep the pending value
            self._buf = self._buf[self._pos:]
            self._pos = 0
        try:
            chunk = self._handle.read(_CHUNK)
        except UnicodeDecodeError as exc:
            raise SnapshotError("The snapshot is not valid UTF-8 text.") from exc
        except OSError as exc:
            raise SnapshotError("The snapshot file cannot be read: {0}".format(exc)) from exc
        if not chunk:
            self._eof = True
            return False
        self._buf += chunk
        return True

    def _skip_ws(self):
        while True:
            buf = self._buf
            pos = self._pos
            while pos < len(buf) and buf[pos] in _WHITESPACE:
                pos += 1
            self._pos = pos
            if pos < len(buf) or not self._fill():
                return

    def peek(self):
        """The next non-whitespace character, or None at the end of the file."""
        self._skip_ws()
        if self._pos >= len(self._buf):
            return None
        return self._buf[self._pos]

    def take(self):
        self._pos += 1

    def expect(self, char, what):
        found = self.peek()
        if found is None:
            raise SnapshotError(
                "The snapshot ends where {0} was expected (truncated file?).".format(what)
            )
        if found != char:
            raise SnapshotError("Expected {0} in {1}, found {2!r}.".format(char, what, found))
        self._pos += 1

    def scalar(self, what):
        """Decode one plain JSON value (string, number, true, false, null)."""
        self._skip_ws()
        while True:
            if self._pos >= len(self._buf):
                raise SnapshotError(
                    "The snapshot ends in the middle of {0} (truncated file?).".format(what)
                )
            try:
                value, end = self._decoder.raw_decode(self._buf, self._pos)
            except json.JSONDecodeError as exc:
                if not self._fill():
                    raise SnapshotError(
                        "The snapshot is corrupt or truncated inside {0}: {1}.".format(what, exc)
                    ) from exc
                if len(self._buf) - self._pos > _MAX_VALUE_CHARS:
                    raise SnapshotError(
                        "The {0} is too large (over {1} characters); the snapshot is refused."
                        .format(what, _MAX_VALUE_CHARS)
                    )
                continue
            if end - self._pos > _MAX_VALUE_CHARS:
                raise SnapshotError(
                    "The {0} is too large (over {1} characters); the snapshot is refused."
                    .format(what, _MAX_VALUE_CHARS)
                )
            if isinstance(value, (dict, list)):
                raise SnapshotError(
                    "The {0} must be a plain value, not a nested object or array.".format(what)
                )
            self._pos = end
            return value


def _skip_value(stream, depth, what):
    """Consume one value of any shape without keeping it (unknown fields)."""
    if depth > _MAX_DEPTH:
        raise SnapshotError(
            "The snapshot nests deeper than {0} levels; it is refused.".format(_MAX_DEPTH)
        )
    found = stream.peek()
    if found is None:
        raise SnapshotError(
            "The snapshot ends in the middle of {0} (truncated file?).".format(what)
        )
    if found == "{":
        stream.take()
        _skip_object_body(stream, depth, what)
    elif found == "[":
        stream.take()
        _skip_array_body(stream, depth, what)
    else:
        stream.scalar(what)


def _skip_object_body(stream, depth, what):
    first = True
    while True:
        found = stream.peek()
        if found is None:
            raise SnapshotError(
                "The snapshot ends in the middle of {0} (truncated file?).".format(what)
            )
        if found == "}":
            stream.take()
            return
        if not first:
            stream.expect(",", what)
        first = False
        key = stream.scalar("an object key inside {0}".format(what))
        if not isinstance(key, str):
            raise SnapshotError("Object keys must be strings inside {0}.".format(what))
        stream.expect(":", "the value of '{0}'".format(key))
        _skip_value(stream, depth + 1, "the value of '{0}'".format(key))


def _skip_array_body(stream, depth, what):
    first = True
    while True:
        found = stream.peek()
        if found is None:
            raise SnapshotError(
                "The snapshot ends in the middle of {0} (truncated file?).".format(what)
            )
        if found == "]":
            stream.take()
            return
        if not first:
            stream.expect(",", what)
        first = False
        _skip_value(stream, depth + 1, "an item inside {0}".format(what))


def _parse_object(stream, what, depth, keep):
    """One JSON object; the keys in ``keep`` are decoded, the rest skipped."""
    stream.expect("{", what)
    result = {}
    first = True
    while True:
        found = stream.peek()
        if found is None:
            raise SnapshotError(
                "The snapshot ends in the middle of {0} (truncated file?).".format(what)
            )
        if found == "}":
            stream.take()
            return result
        if not first:
            stream.expect(",", what)
        first = False
        key = stream.scalar("an object key inside {0}".format(what))
        if not isinstance(key, str):
            raise SnapshotError("Object keys must be strings inside {0}.".format(what))
        stream.expect(":", "the value of '{0}'".format(key))
        if keep is not None and key in keep:
            result[key] = stream.scalar("the value of '{0}'".format(key))
        else:
            _skip_value(stream, depth + 1, "the value of '{0}'".format(key))


def _validate_header(header):
    """The typed header: three known keys, honest refusals for anything else."""
    for key in ("progname", "progver"):
        value = header.get(key)
        if not isinstance(value, str) or not value:
            raise SnapshotError("The header must carry a non-empty string {0}.".format(key))
    timestamp = header.get("timestamp")
    if not _is_count(timestamp):
        raise SnapshotError("The header must carry an integer timestamp (seconds since the epoch).")
    return {
        "progname": header["progname"],
        "progver": header["progver"],
        "timestamp": timestamp,
    }


def _validate_info(info, what):
    name = info.get("name")
    if not isinstance(name, str) or not name:
        raise SnapshotError("{0} must carry a non-empty string name.".format(what))
    if not _is_count(info.get("asize")):
        raise SnapshotError("The entry '{0}' must carry a non-negative integer asize.".format(name))
    for key in ("dsize", "ino", "dev"):
        if key in info and info[key] is not None and not _is_count(info[key]):
            raise SnapshotError("The entry '{0}' has a non-integer {1}.".format(name, key))
    for key in ("read_error", "notreg"):
        if key in info and not isinstance(info[key], bool):
            raise SnapshotError("The entry '{0}' has a non-boolean {1}.".format(name, key))
    if "excluded" in info and info["excluded"] is not None and not isinstance(info["excluded"], str):
        raise SnapshotError("The entry '{0}' has a non-string excluded reason.".format(name))


def _parse_info(stream, nodes, max_nodes, what):
    """One info object; every entry counts against the node budget."""
    info = _parse_object(stream, what, 1, _INFO_KEYS)
    _validate_info(info, what)
    nodes[0] += 1
    if nodes[0] > max_nodes:
        raise SnapshotError(
            "The snapshot holds too many nodes (over the budget of {0}).".format(max_nodes)
        )
    return info


def _node_common(info):
    """The explorer-shaped fields every imported node carries."""
    node = {
        "name": info["name"],
        "sizeBytes": info["asize"],
        "sizeOnDiskBytes": _opt_count(info.get("dsize")),
        "unreadable": 1 if info.get("read_error") else 0,
    }
    if info.get("notreg"):
        node["notregular"] = True
    excluded = info.get("excluded")
    if isinstance(excluded, str) and excluded:
        node["excluded"] = excluded
        if excluded == "budget":  # this writer's reserved reason for truncation
            node["truncated"] = True
    ino = _opt_count(info.get("ino"))
    if ino is not None:
        node["ino"] = ino
    dev = _opt_count(info.get("dev"))
    if dev is not None:
        node["dev"] = dev
    return node


def _file_node(info):
    node = _node_common(info)
    node["files"] = 1
    node["folders"] = 0
    return node


def _dir_node(info, children):
    node = _node_common(info)
    files = 0
    folders = 0
    for child in children:
        files += child.get("files", 0)
        folders += child.get("folders", 0)
        if "children" in child:
            folders += 1
    node["files"] = files
    node["folders"] = folders
    node["children"] = children
    return node


def _parse_item(stream, nodes, max_nodes, depth, what):
    """One child entry: a directory pair ``[info, [children]]`` or a file object."""
    found = stream.peek()
    if found is None:
        raise SnapshotError(
            "The snapshot ends in the middle of {0} (truncated file?).".format(what)
        )
    if found == "[":
        stream.take()
        info = _parse_info(stream, nodes, max_nodes, "a directory inside {0}".format(what))
        stream.expect(",", "the children of '{0}'".format(info["name"]))
        kids = _parse_children(
            stream, nodes, max_nodes, depth + 1, "the children of '{0}'".format(info["name"])
        )
        stream.expect("]", "the directory entry '{0}'".format(info["name"]))
        return _dir_node(info, kids)
    if found == "{":
        info = _parse_info(stream, nodes, max_nodes, "a file inside {0}".format(what))
        return _file_node(info)
    raise SnapshotError(
        "Expected a directory pair or a file object in {0}, found {1!r}.".format(what, found)
    )


def _parse_children(stream, nodes, max_nodes, depth, what):
    if depth > _MAX_DEPTH:
        raise SnapshotError(
            "The snapshot nests deeper than {0} levels; it is refused.".format(_MAX_DEPTH)
        )
    stream.expect("[", what)
    children = []
    first = True
    while True:
        found = stream.peek()
        if found is None:
            raise SnapshotError(
                "The snapshot ends in the middle of {0} (truncated file?).".format(what)
            )
        if found == "]":
            stream.take()
            return children
        if not first:
            stream.expect(",", what)
        first = False
        children.append(_parse_item(stream, nodes, max_nodes, depth, what))


def _parse_document(handle, max_nodes):
    stream = _Stream(handle)
    stream.expect("[", "the start of the snapshot (it must be a JSON array)")
    major = stream.scalar("the format version")
    if not isinstance(major, int) or isinstance(major, bool):
        raise SnapshotError("The format version must be an integer, found {0!r}.".format(major))
    if major != SUPPORTED_MAJOR:
        raise SnapshotError(
            "Unsupported major version {0}: this reader reads major version {1} documents "
            "(minor 1 or 2).".format(major, SUPPORTED_MAJOR)
        )
    stream.expect(",", "the format version")
    minor = stream.scalar("the format version")
    if not isinstance(minor, int) or isinstance(minor, bool):
        raise SnapshotError("The format version must be an integer, found {0!r}.".format(minor))
    if minor not in SUPPORTED_MINORS:
        raise SnapshotError(
            "Unsupported minor version {0}: this reader accepts minor versions {1}."
            .format(minor, " and ".join(str(m) for m in SUPPORTED_MINORS))
        )
    stream.expect(",", "the header object")
    header = _validate_header(_parse_object(stream, "the header object", 1, _HEADER_KEYS))
    stream.expect(",", "the root entry")
    nodes = [0]
    root_info = _parse_info(stream, nodes, max_nodes, "the root entry")
    stream.expect(",", "the root entry's children")
    root_children = _parse_children(stream, nodes, max_nodes, 2, "the root entry's children")
    stream.expect("]", "the end of the snapshot")
    stream._skip_ws()
    if stream._pos < len(stream._buf) or stream._fill():
        raise SnapshotError("The snapshot holds unexpected data after the final ']'.")
    return header, _dir_node(root_info, root_children)


# ------------------------------------------------------------- the writer


def _info_from_node(node, *, is_root, parent_dev):
    """The interchange info object for one node, plus the device it carries."""
    name = node.get("name")
    if not isinstance(name, str) or not name:
        raise SnapshotError("Every node needs a non-empty string name.")
    if is_root:
        path = node.get("path")
        if isinstance(path, str) and path:
            name = path  # the classic tool records the scanned path as the root's name
    if not _is_count(node.get("sizeBytes")):
        raise SnapshotError("The node '{0}' needs a non-negative integer sizeBytes.".format(name))
    info = {"name": name, "asize": node["sizeBytes"]}
    dsize = _opt_count(node.get("sizeOnDiskBytes"))
    if dsize is not None:
        info["dsize"] = dsize
    ino = _opt_count(node.get("ino"))
    if ino is not None:
        info["ino"] = ino
    dev_effective = parent_dev
    dev = _opt_count(node.get("dev"))
    if dev is not None:
        dev_effective = dev
        if is_root or dev != parent_dev:
            info["dev"] = dev
    unreadable = node.get("unreadable", 0)
    if not _is_count(unreadable):
        raise SnapshotError("The node '{0}' has a non-integer unreadable count.".format(name))
    if unreadable > 0:
        info["read_error"] = True
    if node.get("notregular"):
        info["notreg"] = True
    excluded = node.get("excluded")
    if node.get("truncated"):
        info["excluded"] = "budget"
    elif isinstance(excluded, str) and excluded:
        info["excluded"] = excluded
    return info, dev_effective


def _raw_children(node, name):
    raw = node.get("children")
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise SnapshotError("The children of '{0}' must be a list.".format(name))
    return raw


def _build_item(node, parent_dev):
    """One entry: a ``[info, [children]]`` pair for a directory, ``{info}`` for a file."""
    if not isinstance(node, dict):
        raise SnapshotError("Every snapshot node must be a dict, found {0!r}.".format(node))
    if "children" in node:
        info, dev = _info_from_node(node, is_root=False, parent_dev=parent_dev)
        kids = [_build_item(child, dev) for child in _raw_children(node, info["name"])]
        return [info, kids]
    info, _ = _info_from_node(node, is_root=False, parent_dev=parent_dev)
    return info


def _build_root_pair(node):
    """The root is always written as a directory pair (the format's shape)."""
    if not isinstance(node, dict):
        raise SnapshotError("The node to export must be a dict.")
    info, dev = _info_from_node(node, is_root=True, parent_dev=None)
    children = [_build_item(child, dev) for child in _raw_children(node, info["name"])]
    return info, children, dev


def _check_destination(out_path):
    if isinstance(out_path, os.PathLike):
        out_path = os.fspath(out_path)
    if not isinstance(out_path, str) or not out_path:
        raise SnapshotError("The snapshot destination must be a non-empty path.")
    if os.path.islink(out_path):
        raise SnapshotError("The snapshot destination must not be a symlink: {0}".format(out_path))
    parent = os.path.dirname(os.path.abspath(out_path))
    if not os.path.isdir(parent):
        raise SnapshotError("The snapshot folder does not exist: {0}".format(parent))
    if os.path.islink(parent):
        raise SnapshotError("The snapshot folder must not be a symlink: {0}".format(parent))
    if os.name != "nt" and stat.S_IMODE(os.stat(parent).st_mode) & 0o077:
        raise SnapshotError("The snapshot folder must be private (mode 0700): {0}".format(parent))
    return out_path


def _atomic_write(out_path, body):
    tmp = out_path + ".tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, out_path)
    except OSError as exc:
        _silent_unlink(tmp)
        raise SnapshotError(
            "The snapshot cannot be written to {0}: {1}".format(out_path, exc)
        ) from exc
    except BaseException:
        _silent_unlink(tmp)
        raise
    _fsync_dir(os.path.dirname(os.path.abspath(out_path)))
    return out_path


# ------------------------------------------------------------- public API


def export_snapshot(node, out_path, *, progver=WRITER_VERSION, env=None, platform=None):
    """Freeze an explorer-style node tree into the interchange format.

    ``node`` is a dict in the explorer's shape: ``name``, ``sizeBytes`` (the
    parent-summed apparent size) and ``children`` for directories — a node
    without ``children`` is written as a plain file — plus the optional
    markers ``sizeOnDiskBytes``, ``unreadable``, ``notregular``, ``excluded``
    and ``truncated``. Counts the format cannot carry (``files``, ``folders``,
    ``ignored``) are re-derived from the entries on import or dropped.

    The write is atomic: a ``0600`` temporary file, fsync, ``os.replace`` and
    a best-effort directory fsync — a crash never leaves a half-written
    snapshot and no ``.tmp`` survives, not even a failed one. The destination
    must not be a symlink; its folder must exist, must not be a symlink and
    must be private (mode ``0700``) on POSIX.

    ``env`` and ``platform`` are accepted for call-site symmetry with the
    other engine entry points; the exchange format carries no host data.
    Returns ``out_path``. This is the only write this module ever performs.
    """
    if not isinstance(progver, str) or not progver:
        raise SnapshotError("progver must be a non-empty string.")
    root_info, root_children, _ = _build_root_pair(node)
    out_path = _check_destination(out_path)
    header = {"progname": PROGNAME, "progver": progver, "timestamp": int(time.time())}
    body = json.dumps(
        [SUPPORTED_MAJOR, 1, header, root_info, root_children], ensure_ascii=True
    ) + "\n"
    return _atomic_write(out_path, body)


def read_snapshot(path, *, max_nodes=DEFAULT_MAX_NODES):
    """Read a snapshot document back into an explorer-shaped node tree.

    The parse is streaming: the document is consumed piece by piece against a
    node budget (``max_nodes``), so an oversized or hostile file is refused
    instead of loaded — exceeding the budget raises :class:`SnapshotError`
    ("too many nodes"). Major version 1 with minor version 1 or 2 is
    accepted; anything else, a wrong header shape, a corrupt or truncated
    document, an oversized string or a symlinked path is refused with the
    honest reason.

    The mapping: ``asize`` becomes ``sizeBytes``, ``dsize`` becomes
    ``sizeOnDiskBytes`` (``None`` when the file does not carry it),
    ``notreg`` becomes ``notregular``, ``excluded`` becomes ``excluded``
    (the reserved reason ``"budget"`` also restores ``truncated``) and
    ``read_error`` becomes ``unreadable: 1`` — the format records the fact,
    not the count. ``files`` and ``folders`` counts are re-derived from the
    entries; ``ino`` and ``dev`` pass through when the document carries them.

    Returns ``{"header": {...}, "root": <node dict>}``. Like every read in
    this module, this touches nothing but the file it opens
    (``import_is_read_only``).
    """
    if not _is_count(max_nodes) or max_nodes < 1:
        raise SnapshotError("max_nodes must be a positive integer.")
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    if not isinstance(path, str) or not path:
        raise SnapshotError("The snapshot path must be a non-empty string.")
    if os.path.islink(path):
        raise SnapshotError("The snapshot file must not be a symlink: {0}".format(path))
    if not os.path.exists(path):
        raise SnapshotError("The snapshot file does not exist: {0}".format(path))
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError as exc:
        raise SnapshotError("The snapshot file cannot be opened: {0}".format(exc)) from exc
    with handle:
        header, root = _parse_document(handle, max_nodes)
    return {"header": header, "root": root}


def _diff_input(value, side):
    """Whatever the caller handed in, resolved to a root node dict."""
    if isinstance(value, (str, os.PathLike)):
        return read_snapshot(value)["root"]
    if isinstance(value, dict):
        root = value.get("root")
        if root is not None or "root" in value:
            if isinstance(root, dict):
                return root
            raise SnapshotError(
                "The {0} snapshot result's root must be a node dict.".format(side)
            )
        if isinstance(value.get("name"), str) and _is_count(value.get("sizeBytes")):
            return value
        raise SnapshotError(
            "The {0} argument must be a snapshot path, a read_snapshot result, "
            "or a node dict.".format(side)
        )
    raise SnapshotError(
        "The {0} argument must be a snapshot path, a read_snapshot result, or a node dict."
        .format(side)
    )


def _check_prefix(prefix):
    if prefix is None:
        return None
    if isinstance(prefix, str) or not isinstance(prefix, (list, tuple)):
        raise SnapshotError("The prefix must be None or a list of non-empty child names.")
    if not prefix:
        return None
    for name in prefix:
        if not isinstance(name, str) or not name:
            raise SnapshotError("The prefix must be None or a list of non-empty child names.")
    return list(prefix)


def _check_depth(depth):
    if depth is None:
        return None
    if not _is_count(depth) or depth < 1:
        raise SnapshotError("depth must be None or a positive integer.")
    return depth


def _check_limit(limit):
    if not _is_count(limit):
        raise SnapshotError("summary_limit must be a non-negative integer.")
    return limit


def _size(node):
    value = node.get("sizeBytes")
    if not _is_count(value):
        raise SnapshotError(
            "The node '{0}' has no usable sizeBytes for the diff.".format(node.get("name", "?"))
        )
    return value


def _disk(node):
    return _opt_count(node.get("sizeOnDiskBytes"))


def _is_dir(node):
    return isinstance(node.get("children"), list)


def _children_by_name(node):
    children = node.get("children") if isinstance(node, dict) else None
    if not isinstance(children, list):
        return {}
    result = {}
    for child in children:
        if isinstance(child, dict) and isinstance(child.get("name"), str):
            result.setdefault(child["name"], child)
    return result


def _emit(acc, limit, key, entry):
    if len(acc[key]) < limit:
        acc[key].append(entry)
    else:
        acc["more"][key] = acc["more"].get(key, 0) + 1


def _count_changes(old_dir, new_dir):
    """The added/removed entries the detail walk would list below this pair."""
    old_map = _children_by_name(old_dir)
    new_map = _children_by_name(new_dir)
    added = 0
    removed = 0
    for name, new_child in new_map.items():
        old_child = old_map.get(name)
        if old_child is None:
            added += 1
        elif _is_dir(old_child) and _is_dir(new_child):
            deep_added, deep_removed = _count_changes(old_child, new_child)
            added += deep_added
            removed += deep_removed
    for name in old_map:
        if name not in new_map:
            removed += 1
    return added, removed


def _diff_pair(old_child, new_child, rel_parts, level, depth, limit, acc):
    path = "/".join(rel_parts)
    old_size = _size(old_child)
    new_size = _size(new_child)
    both_dirs = _is_dir(old_child) and _is_dir(new_child)
    if depth is not None and level >= depth and both_dirs:
        # past the detail cut: fold everything below into one summarized entry
        added, removed = _count_changes(old_child, new_child)
        net = new_size - old_size
        if added or removed or net != 0:
            _emit(acc, limit, "summarized", {
                "path": path, "addedCount": added, "removedCount": removed, "netBytes": net,
            })
        else:
            acc["unchanged"] += 1
        return
    if new_size > old_size:
        _emit(acc, limit, "grown", {
            "path": path, "oldBytes": old_size, "newBytes": new_size, "delta": new_size - old_size,
        })
    elif new_size < old_size:
        _emit(acc, limit, "shrunk", {
            "path": path, "oldBytes": old_size, "newBytes": new_size, "delta": new_size - old_size,
        })
    else:
        acc["unchanged"] += 1
    old_disk = _disk(old_child)
    new_disk = _disk(new_child)
    if old_disk is not None and new_disk is not None:
        if new_disk > old_disk:
            _emit(acc, limit, "grownOnDisk", {
                "path": path, "oldBytes": old_disk, "newBytes": new_disk,
                "delta": new_disk - old_disk,
            })
        elif new_disk < old_disk:
            _emit(acc, limit, "shrunkOnDisk", {
                "path": path, "oldBytes": old_disk, "newBytes": new_disk,
                "delta": new_disk - old_disk,
            })
    if both_dirs:
        _diff_children(old_child, new_child, rel_parts, level + 1, depth, limit, acc)


def _diff_children(old_dir, new_dir, rel_parts, level, depth, limit, acc):
    old_map = _children_by_name(old_dir)
    new_map = _children_by_name(new_dir)
    names = list(new_map) + [name for name in old_map if name not in new_map]
    for name in names:
        child_rel = rel_parts + [name]
        old_child = old_map.get(name)
        new_child = new_map.get(name)
        if old_child is not None and new_child is not None:
            _diff_pair(old_child, new_child, child_rel, level, depth, limit, acc)
        elif new_child is not None:
            size = _size(new_child)
            _emit(acc, limit, "added", {"path": "/".join(child_rel), "oldBytes": 0,
                                        "newBytes": size, "delta": size})
        else:
            size = _size(old_child)
            _emit(acc, limit, "removed", {"path": "/".join(child_rel), "oldBytes": size,
                                          "newBytes": 0, "delta": -size})


def diff_snapshots(old, new, *, prefix=None, depth=None, summary_limit=5):
    """Compare two snapshots and report what changed, matched by child name.

    ``old`` and ``new`` are snapshot file paths, :func:`read_snapshot`
    results or plain node dicts — whatever resolves to a root node. Children
    are matched by name at every level and the walk reports, per changed
    node: ``added`` / ``removed`` (a subtree on one side only, reported once
    for its top, never recursed into), ``grown`` / ``shrunk`` (a matched
    node whose apparent size changed), ``grownOnDisk`` / ``shrunkOnDisk``
    (the same for on-disk bytes, compared only when both sides carry
    ``sizeOnDiskBytes``) and ``unchanged`` (the count of matched nodes whose
    apparent size is equal). Every size entry is
    ``{"path", "oldBytes", "newBytes", "delta"}``.

    Paths are name paths relative to the comparison root, joined with ``/``.
    ``prefix`` (a list of child names) limits the comparison to that
    subtree: the prefix node itself is the comparison root and is never
    reported — unless it is missing on exactly one side, where the whole
    subtree is reported as one added or removed entry. A prefix missing on
    both sides is refused.

    ``depth`` stops the per-node detail at that many child-hops below the
    comparison root and folds everything below into one ``summarized``
    entry per directory — ``{"path", "addedCount", "removedCount",
    "netBytes"}`` — where the counts are the entries the detail walk would
    have listed and ``netBytes`` is the directory's whole size change.
    ``summary_limit`` caps every list; the overflow is noted in ``more``
    (``None`` when nothing overflowed). ``unchanged`` is a count and is
    never capped.

    Diffing reads apparent sizes and touches nothing but the snapshot files
    it is given (``import_is_read_only``).
    """
    old_root = _diff_input(old, "old")
    new_root = _diff_input(new, "new")
    prefix = _check_prefix(prefix)
    depth = _check_depth(depth)
    limit = _check_limit(summary_limit)
    acc = {
        "added": [], "removed": [], "grown": [], "shrunk": [],
        "grownOnDisk": [], "shrunkOnDisk": [], "summarized": [],
        "unchanged": 0, "more": {},
    }
    if prefix is not None:
        old_sub = _descend(old_root, prefix)
        new_sub = _descend(new_root, prefix)
        if old_sub is None and new_sub is None:
            raise SnapshotError(
                "The prefix '{0}' does not exist in either snapshot.".format("/".join(prefix))
            )
        path = "/".join(prefix)
        if old_sub is None:
            size = _size(new_sub)
            _emit(acc, limit, "added", {"path": path, "oldBytes": 0, "newBytes": size,
                                        "delta": size})
        elif new_sub is None:
            size = _size(old_sub)
            _emit(acc, limit, "removed", {"path": path, "oldBytes": size, "newBytes": 0,
                                          "delta": -size})
        else:
            _diff_children(old_sub, new_sub, list(prefix), 1, depth, limit, acc)
    else:
        _diff_children(old_root, new_root, [], 1, depth, limit, acc)
    acc["more"] = acc["more"] or None
    return acc


def _descend(root, names):
    """The node at the prefix's name path, or None when a component is missing."""
    current = root
    for name in names:
        if current is None or not _is_dir(current):
            return None
        nxt = None
        for child in current["children"]:
            if isinstance(child, dict) and child.get("name") == name:
                nxt = child
                break
        current = nxt
    return current


__all__ = ["SnapshotError", "export_snapshot", "read_snapshot", "diff_snapshots"]
