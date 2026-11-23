"""Step 2 of a scan: look for dangerous patterns in the extension's JavaScript.

Plain text search gives false alarms ("eval(" inside a comment) and misses
hidden calls (self["ev" + "al"]). So each file is cleaned first:
  1. comments are blanked out,
  2. string pieces joined with + are folded ("ev" + "al" -> "eval"),
  3. the inside of strings is masked, so text in strings is ignored. Code inside
     template interpolations (`${...}`) is kept, because it runs.
Newlines are kept, so line numbers stay correct.
"""
import bisect
import re
from pathlib import Path

from . import Finding

MAX_FILE = 2 * 1024 * 1024                 # larger files are reported, not scanned
SCRIPT_SUFFIXES = {".js", ".mjs", ".cjs"}  # classic scripts and ES modules


def strip_comments(src):
    """Blank out // and /* */ comments, keep strings and newlines."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":                      # copy a string literal as is
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("//", i):        # line comment
            j = src.find("\n", i)
            i = n if j == -1 else j
        elif src.startswith("/*", i):        # block comment, keep its newlines
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("\n" * src.count("\n", i, j))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


_CONCAT = re.compile(r"""(["'])((?:(?!\1)[^\\\n])*)\1\s*\+\s*(["'])((?:(?!\3)[^\\\n])*)\3""")


def fold_strings(code):
    """'ev' + "al" -> "eval" (repeated until nothing changes)."""
    while True:
        new = _CONCAT.sub(lambda m: '"' + m.group(2) + m.group(4) + '"'
                          + "\n" * m.group(0).count("\n"), code)
        if new == code:
            return code
        code = new


def _skip_string(code, i):
    """Index just after the quoted string that starts at code[i]."""
    quote, j, n = code[i], i + 1, len(code)
    while j < n and code[j] != quote:
        j += 2 if code[j] == "\\" else 1
    return j + 1


def string_ranges(code, offset=0):
    """(start, end) of every piece of string *text*; template ${...} code is excluded."""
    ranges, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c in "'\"":
            end = _skip_string(code, i)
            ranges.append((offset + i + 1, offset + min(end - 1, n)))
            i = end
        elif c == "`":
            j, start = i + 1, i + 1
            while j < n and code[j] != "`":
                if code[j] == "\\":
                    j += 2
                elif code.startswith("${", j):
                    ranges.append((offset + start, offset + j))
                    k, depth = j + 2, 1          # find the matching }
                    while k < n and depth:
                        if code[k] in "'\"`":
                            k = _skip_string(code, k)
                            continue
                        depth += {"{": 1, "}": -1}.get(code[k], 0)
                        k += 1
                    ranges += string_ranges(code[j + 2:k - 1], offset + j + 2)
                    j = start = k
                else:
                    j += 1
            ranges.append((offset + start, offset + min(j, n)))
            i = j + 1
        else:
            i += 1
    return ranges


def mask_strings(code, ranges=None):
    """Replace string text with spaces (keeps length, quotes and newlines)."""
    chars = list(code)
    for start, end in ranges if ranges is not None else string_ranges(code):
        for k in range(start, end):
            if chars[k] != "\n":
                chars[k] = " "
    return "".join(chars)


# (rule, severity, points, regex, message, searched text)
# "masked" = string text hidden; "folded" = string text visible, used when the
# pattern itself contains a string ('eval', 'iframe'). A folded match that starts
# inside a string is ignored, so an example written in a string is not reported.
RULES = [
    ("CODE-EVAL", "high", 18, r"\beval\s*\(", "eval() runs text as code", "masked"),
    ("CODE-HIDDEN-EVAL", "critical", 35, r"\[\s*[\"'](?:eval|Function)[\"']\s*\]\s*\(",
     "hidden eval: called through a string name like self['ev'+'al'](...)", "folded"),
    ("CODE-FUNCTION", "high", 18, r"\b(?:new\s+)?Function\s*\(",
     "Function() constructor builds code from text", "masked"),
    ("CODE-STRING-TIMER", "medium", 8, r"\bset(?:Timeout|Interval)\s*\(\s*[\"'`]",
     "setTimeout/setInterval with a string runs it as code", "folded"),
    ("CODE-EXECUTE-SCRIPT", "high", 18, r"\.executeScript\s*\(",
     "executeScript injects code into web pages", "masked"),
    ("CODE-USER-SCRIPTS", "high", 18, r"\b(?:chrome|browser)\.userScripts\.register\s*\(",
     "userScripts.register adds scripts that run in web pages", "masked"),
    ("CODE-IFRAME-INJECT", "medium", 8, r"createElement\s*\(\s*[\"']iframe[\"']",
     "creates an iframe inside the page", "folded"),
    ("CODE-SCRIPT-INJECT", "high", 18, r"createElement\s*\(\s*[\"']script[\"']",
     "creates a <script> element (can load or run downloaded code)", "folded"),
    ("CODE-COOKIE-READ", "medium", 8,
     r"\b(?:chrome|browser)\.cookies\.get(?:All)?\s*\(|\bdocument\s*(?:\.\s*cookie\b|\[\s*[\"']cookie[\"']\s*\])",
     "reads cookies", "folded"),
    ("CODE-NETWORK", "info", 0,
     r"\bfetch\s*\(|\.open\s*\(\s*[\"'](?:GET|POST|PUT|PATCH|DELETE|HEAD)[\"']|\bsendBeacon\s*\("
     r"|\bnew\s+(?:WebSocket|EventSource)\s*\(|\bimportScripts\s*\(",
     "sends network requests", "folded"),
]
_COMPILED = [(r, s, p, re.compile(rx, re.I if r == "CODE-NETWORK" else 0), m, t)
             for r, s, p, rx, m, t in RULES]
_URL = re.compile(r"(?:https?|wss?)://[^\s\"'`]+")
# Ways to turn downloaded text into running code.
_DYNAMIC = {"CODE-EVAL", "CODE-HIDDEN-EVAL", "CODE-FUNCTION", "CODE-STRING-TIMER",
            "CODE-SCRIPT-INJECT"}


def scan_source(src, name):
    """Findings and URL endpoints for one JavaScript file."""
    folded = fold_strings(strip_comments(src))
    ranges = string_ranges(folded)
    texts = {"folded": folded, "masked": mask_strings(folded, ranges)}
    starts = [s for s, _ in ranges]
    newlines = [i for i, ch in enumerate(folded) if ch == "\n"]

    def in_string(pos):
        k = bisect.bisect_right(starts, pos) - 1
        return k >= 0 and ranges[k][0] <= pos < ranges[k][1]

    findings = []
    for rule, severity, points, regex, message, which in _COMPILED:
        for m in regex.finditer(texts[which]):
            if which == "folded" and in_string(m.start()):
                continue
            line = bisect.bisect_right(newlines, m.start() - 1) + 1
            findings.append(Finding(rule, severity, points, message, name, line))

    # Correlations inside one file: the patterns are risky together.
    hits = {f.rule: f for f in findings}
    network = hits.get("CODE-NETWORK")
    dynamic = next((f for f in findings if f.rule in _DYNAMIC), None)
    if network and dynamic:
        findings.append(Finding(
            "CODE-TWO-STAGE", "critical", 35,
            "downloads data and runs code from text in the same file "
            "(two-stage payload, 'clean dropper')", name, dynamic.line))
    if network and "CODE-COOKIE-READ" in hits:
        findings.append(Finding(
            "CODE-COOKIE-EXFIL", "high", 18,
            "reads cookies and sends network requests in the same file "
            "(possible exfiltration)", name, hits["CODE-COOKIE-READ"].line))

    endpoints = sorted(set(_URL.findall(folded)))
    return findings, endpoints


def scan_scripts(folder):
    """Scan every script file under the extension folder."""
    folder = Path(folder)
    findings, endpoints = [], set()
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in SCRIPT_SUFFIXES or not path.is_file():
            continue
        name = path.relative_to(folder).as_posix()
        try:
            if path.stat().st_size > MAX_FILE:
                # Never let a skipped file look clean.
                findings.append(Finding("SCAN-SKIPPED-LARGE", "medium", 8,
                                        "file is over 2 MiB and was not scanned", name))
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:            # removed or locked while scanning
            findings.append(Finding("SCAN-UNREADABLE", "medium", 8,
                                    f"file could not be read ({exc.__class__.__name__})", name))
            continue
        file_findings, file_endpoints = scan_source(src, name)
        findings += file_findings
        endpoints.update(file_endpoints)
    return findings, sorted(endpoints)
