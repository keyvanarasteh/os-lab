# OS-24 Local .deb Installer - Verification

## Environment
- OS: Ubuntu Server 26.04.1 LTS
- Shell: Bash
- Project: os-lab
- Task: OS-24 Local .deb Installer

## Purpose
This script installs a local Debian (.deb) package on Ubuntu.

## Verification Plan
1. Check Bash syntax.
2. Test missing arguments.
3. Test nonexistent package files.
4. Test invalid .deb packages.
5. Test installation preview and confirmation.
6. Verify successful package installation.

## Test Results

### Test 1 - Bash Syntax
Command: bash -n linux-lab/scripts/deb_install.sh
Result: PASS - No syntax errors.

### Test 2 - Missing Argument
Command: bash linux-lab/scripts/deb_install.sh
Result: PASS - Usage message displayed.

### Test 3 - Missing Package File
Command: bash linux-lab/scripts/deb_install.sh olmayan-paket.deb
Result: PASS - Missing package was rejected.

### Test 4 - Invalid Package
Command: touch sahte.deb && bash linux-lab/scripts/deb_install.sh sahte.deb
Result: PASS - Invalid package was rejected.

### Test 5 - Real Package Installation
Package: hello
Command: bash linux-lab/scripts/deb_install.sh hello_*.deb
Result: PASS - Package installation completed.

### Test 6 - Installation Verification
Command: dpkg -s hello | grep Status
Output: Status: install ok installed
Result: PASS - Package installation verified.
