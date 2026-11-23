# OS-24 - Local .deb Installer Report

## Project Information
- Project: os-lab
- Task: OS-24 Local .deb Installer
- Operating System: Ubuntu Server 26.04.1 LTS
- Language: Bash

## Project Purpose
The purpose of this project is to develop a Bash script that installs local Debian (.deb) packages on Ubuntu safely.

## Implementation
The installer is located at:
`linux-lab/scripts/deb_install.sh`

The script:
1. Checks the provided package argument.
2. Validates the .deb file.
3. Creates a temporary copy of the package.
4. Displays the installation plan.
5. Requests user confirmation.
6. Installs the package using apt-get.
7. Verifies the installation using dpkg-query.

A compatible script is also available at:
`linux-lab/scripts/os-24-deb-installer.sh`

## Testing
The following tests were performed:
- Bash syntax validation: PASS
- Missing argument: PASS
- Missing package file: PASS
- Invalid .deb package: PASS
- Real package installation (hello): PASS
- Package installation verification: PASS

The hello package was successfully installed and verified with:
`dpkg -s hello | grep Status`

Result: `Status: install ok installed`

## Conclusion
The OS-24 installer was implemented and tested successfully on Ubuntu Server. The script validates local Debian packages before installation and verifies the installation result.

## What I Learned

During this project, I learned how to fork an open-source repository,
create a Git branch, commit changes, and push them to GitHub.

I also learned how to create a Pull Request, test a Bash script,
and document the results using VERIFY.md and REPORT.md.
