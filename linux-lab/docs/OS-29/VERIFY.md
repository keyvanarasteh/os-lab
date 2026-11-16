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
5. Exit the program.

## Testing
- Operating system: Ubuntu Linux
- Bash syntax check: `bash -n linux-lab/scripts/log-viewer.sh`
- Syntax check result: PASSED

## Expected Result
The script displays an interactive menu. The user selects an option to view or count log entries. Press Ctrl+C to stop live log monitoring.

Note: The specified log file must exist and be readable.

## Student
Aydoğan Bodur  
Student Number: 2620511134
