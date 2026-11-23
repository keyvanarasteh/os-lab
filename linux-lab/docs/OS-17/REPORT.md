# OS-17 — SSH Connection Troubleshooter

## Project Summary
This project implements a Python-based SSH connection troubleshooting tool for OS-17.

The tool analyzes common SSH error messages and provides explanations and suggested solutions.

## Features
The script detects five common SSH problems:

1. Connection timed out
2. Authentication failure (including "wrong password" / "incorrect password")
3. Loopback address (any 127.x.x.x, `::1` or `localhost`; checked before the timeout rule)
4. Firewall restrictions
5. Incorrect network adapter

## Implementation
- Programming language: Python 3
- Script: `linux-lab/scripts/ssh_doctor.py`
- Uses Python standard libraries
- No additional Python packages required

## Testing
Five manual tests were performed successfully.

All five error categories returned the expected results.

Detailed verification commands and results are documented in `linux-lab/docs/OS-17/VERIFY.md`. Review fixes (24.11, instructor patch): script renamed to `ssh_doctor.py` to match the dashboard, scoped/control-byte `--host` input rejected, wider loopback and password detection, and 8 regression tests in `linux-lab/tests/test_ssh_doctor.py`.

## What I Learned
During this project, I learned how to:

- Create a Git branch
- Write and run a Python script
- Diagnose common SSH connection errors
- Document and verify program behavior
- Prepare a contribution using Git and GitHub

## Limitations
The tool classifies supplied error messages. It does not perform live SSH connection checks or automatically modify firewall and network settings.

## Conclusion
The OS-17 SSH Connection Troubleshooter provides a simple command-line tool for identifying common SSH errors and suggesting possible fixes.
