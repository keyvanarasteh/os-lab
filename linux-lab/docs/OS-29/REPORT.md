# OS-29 - Project Report

## Project Information
**Project:** Server Log Viewer Helper (OS-29)  
**Student:** Aydoğan Bodur  
**Student Number:** 2620511134  
**Course:** Open Source Operating Systems

## Project Purpose
The purpose of this project is to develop a simple Bash script for viewing and monitoring Linux system logs.

## Implementation
I created a menu-based Bash script named `log-viewer.sh` in the `linux-lab/scripts/` directory.

The script provides the following functions:

1. Display the first 20 log entries.
2. Open and read the log file.
3. Follow new log entries in real time.
4. Count the total number of log lines.
5. Exit the program.

The script uses standard Linux commands such as `head`, `less`, `tail`, and `wc`.

## Testing
The project was developed using Ubuntu Linux.

I checked the Bash syntax using:

`bash -n linux-lab/scripts/log-viewer.sh`

The syntax check completed successfully.

I also demonstrated the script's menu and functions in a screen recording.

## Git and GitHub Experience
During this project, I learned how to work with a GitHub repository, create a branch, add files, commit changes, and open a Pull Request.

I submitted my contribution to the original `keyvanarasteh/os-lab` repository for review.

## Conclusion
This project helped me practice Bash scripting, Linux log monitoring, and the GitHub contribution workflow.

## Pull Request
https://github.com/keyvanarasteh/os-lab/pull/273
