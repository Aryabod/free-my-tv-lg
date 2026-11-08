@echo off
rem Renews LG Developer Mode for Free My TV, for Windows' Task Scheduler (weekly is plenty; it lasts about 40 days):
rem   schtasks /create /tn "FreeMyTV Renew" /sc weekly /d SUN /st 20:00 /tr "\"C:\path\to\webos\renew-weekly.cmd\""
rem The TV's address goes in webos\tv-ip.txt (one line, e.g. 192.168.1.50). The TV must be on and on the same Wi-Fi;
rem if it isn't, renew.log says so and the next run tries again.
cd /d "%~dp0"
set /p TV_IP=<tv-ip.txt
echo ==== %date% %time% >> renew.log
python -I renew.py %TV_IP% >> renew.log 2>&1
