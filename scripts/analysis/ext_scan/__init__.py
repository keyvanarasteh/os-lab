"""PENT-02 browser extension scanner.

Reads an unpacked Chrome/Firefox extension (Manifest V2 or V3), audits what it
asks for (manifest) and what its scripts do (code patterns), and gives a 0-100
risk score. Lab use only: scan extensions you wrote or may legally test.
"""
from dataclasses import asdict, dataclass

__version__ = "0.1.0"


@dataclass
class Finding:
    rule: str          # short id, e.g. PERM-COOKIES
    severity: str      # info | low | medium | high | critical
    points: int        # contribution to the risk score
    message: str       # one line for humans
    file: str = "manifest.json"
    line: int = 0      # 0 = whole file

    def to_dict(self):
        return asdict(self)
