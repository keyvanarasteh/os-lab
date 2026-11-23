# OS-29 - Verification

## Project
Server Log Viewer Helper

## Run Command
```bash
bash linux-lab/scripts/log-viewer.sh /var/log/syslog
```

## Features
1. Display the first 20 log entries.
2. Display the last 20 log entries.
3. Follow log entries in real time.
4. Count the total log lines.
5. Page through the log.
6. Search the log.
7. Exit the program.

## Testing
- Operating system: Ubuntu Linux
- Bash syntax check: `bash -n linux-lab/scripts/log-viewer.sh`
- Syntax check result: PASSED
- Regression tests: `python3 -m pytest linux-lab/tests/test_log_viewer.py` (8 passed, run by the instructor on macOS in a sandbox; the live Ubuntu run is the student's recording)

## Expected Result
The script displays an interactive menu. The user selects an option to view or count log entries. Press Ctrl+C to stop live log monitoring.

Note: The specified log file must exist and be readable.

## Student
Aydoğan Bodur  
Student Number: 2620511134
