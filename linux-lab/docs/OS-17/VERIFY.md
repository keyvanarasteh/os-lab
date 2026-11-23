# OS-17 SSH Connection Troubleshooter — Verification

## Environment
- Operating System: Windows 11
- Terminal: Git Bash
- Language: Python 3
- Task: OS-17

## Manual Tests

### Test 1 — Connection Timeout
Command:
`python3 linux-lab/scripts/ssh_doctor.py "Connection timed out"`

Expected result: `TIMEOUT`

Actual result: `TIMEOUT`

Status: PASS

### Test 2 — Authentication Failure
Command:
`python3 linux-lab/scripts/ssh_doctor.py "Permission denied"`

Expected result: `AUTHENTICATION`

Actual result: `AUTHENTICATION`

Status: PASS

### Test 3 — Loopback Address
Command:
`python3 linux-lab/scripts/ssh_doctor.py "127.0.1.1"`

Expected result: `LOOPBACK`

Actual result: `LOOPBACK`

Status: PASS

### Test 4 — Firewall Block
Command:
`python3 linux-lab/scripts/ssh_doctor.py "Firewall blocked"`

Expected result: `FIREWALL`

Actual result: `FIREWALL`

Status: PASS

### Test 5 — Wrong Network Adapter
Command:
`python3 linux-lab/scripts/ssh_doctor.py "Wrong adapter"`

Expected result: `ADAPTER`

Actual result: `ADAPTER`

Status: PASS

## Conclusion
All five manual SSH error classification tests passed successfully.

The script identifies common SSH connection problems and provides troubleshooting suggestions.

Note: These tests verify message classification, not live SSH connectivity.

## Automated tests
`python3 -m pytest linux-lab/tests/test_ssh_doctor.py` (8 passed; run by the instructor on macOS in a sandbox on 24.11). The five manual tests above were run by the student on Windows 11 with the earlier file name; the commands use the current name and `python3`.
