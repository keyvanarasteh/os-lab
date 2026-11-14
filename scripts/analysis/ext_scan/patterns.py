"""Step 2 of a scan: look for dangerous patterns in the extension's JavaScript.

Plain text search gives false alarms ("eval(" inside a comment) and misses
hidden calls (self["ev" + "al"]). So each file is cleaned first:
  1. comments are blanked out,
  2. string pieces joined with + are folded ("ev" + "al" -> "eval"),
  3. for most rules the inside of strings is masked, so text in strings is ignored.
Newlines are kept, so line numbers stay correct.
"""
import re
from pathlib import Path

from . import Finding

MAX_FILE = 2 * 1024 * 1024  # skip files over 2 MiB


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
            j = n if j == -1 else j
            i = j
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


_STRING = re.compile(r"""(["'`])(?:\\.|(?!\1).)*\1""", re.S)


def mask_strings(code):
    """Replace the inside of every string with spaces (keeps newlines)."""
    return _STRING.sub(lambda m: m.group(0)[0]
                       + re.sub(r"[^\n]", " ", m.group(0)[1:-1])
                       + m.group(0)[-1], code)


# (rule, severity, points, regex, message, searched text)
# "masked" = strings hidden, "folded" = strings visible (after folding).
RULES = [
    ("CODE-EVAL", "high", 18, r"\beval\s*\(", "eval() runs text as code", "masked"),
    ("CODE-HIDDEN-EVAL", "critical", 35, r"\[\s*[\"'](?:eval|Function)[\"']\s*\]",
     "hidden eval: called through a string name like self['ev'+'al']", "folded"),
    ("CODE-FUNCTION", "high", 18, r"\b(?:new\s+)?Function\s*\(",
     "Function() constructor builds code from text", "masked"),
    ("CODE-STRING-TIMER", "medium", 8, r"\bset(?:Timeout|Interval)\s*\(\s*[\"'`]",
     "setTimeout/setInterval with a string runs it as code", "folded"),
    ("CODE-EXECUTE-SCRIPT", "high", 18, r"\.executeScript\s*\(",
     "executeScript injects code into web pages", "masked"),
    ("CODE-IFRAME-INJECT", "medium", 8, r"createElement\s*\(\s*[\"']iframe[\"']",
     "creates an iframe inside the page", "folded"),
    ("CODE-SCRIPT-INJECT", "high", 18, r"createElement\s*\(\s*[\"']script[\"']",
     "creates a <script> element (can load remote code)", "folded"),
    ("CODE-COOKIE-READ", "medium", 8, r"chrome\.cookies\.get(?:All)?\s*\(|document\.cookie\b",
     "reads cookies", "masked"),
    ("CODE-NETWORK", "info", 0, r"\bfetch\s*\(|\bXMLHttpRequest\b|\bsendBeacon\s*\(",
     "sends network requests", "masked"),
]
_COMPILED = [(r, s, p, re.compile(rx), m, t) for r, s, p, rx, m, t in RULES]
_URL = re.compile(r"https?://[^\s\"'`]+")
_DYNAMIC = {"CODE-EVAL", "CODE-HIDDEN-EVAL", "CODE-FUNCTION", "CODE-STRING-TIMER"}


def scan_source(src, name):
    """Findings and URL endpoints for one JavaScript file."""
    folded = fold_strings(strip_comments(src))
    texts = {"folded": folded, "masked": mask_strings(folded)}
    findings = []
    for rule, severity, points, regex, message, which in _COMPILED:
        for m in regex.finditer(texts[which]):
            line = texts[which].count("\n", 0, m.start()) + 1
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
    """Scan every .js file under the extension folder."""
    folder = Path(folder)
    findings, endpoints = [], set()
    for path in sorted(folder.rglob("*.js")):
        if path.stat().st_size > MAX_FILE:
            continue
        name = path.relative_to(folder).as_posix()
        src = path.read_text(encoding="utf-8", errors="replace")
        file_findings, file_endpoints = scan_source(src, name)
        findings += file_findings
        endpoints.update(file_endpoints)
    return findings, sorted(endpoints)
