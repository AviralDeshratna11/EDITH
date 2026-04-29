@echo off
:: EDITH AR — Windows Firewall Setup
:: Run this as Administrator (right-click → Run as administrator)

echo.
echo  E.D.I.T.H — Firewall Configuration
echo  =====================================
echo.

:: Remove old rule if exists
netsh advfirewall firewall delete rule name="EDITH AR Backend" >nul 2>&1

:: Add inbound rule for port 8000
netsh advfirewall firewall add rule ^
  name="EDITH AR Backend" ^
  dir=in ^
  action=allow ^
  protocol=TCP ^
  localport=8000 ^
  description="EDITH AR Assistant backend for Magic Leap 2"

if %errorlevel% == 0 (
  echo  [OK] Firewall rule added for port 8000
) else (
  echo  [ERROR] Failed - make sure you ran as Administrator
  pause
  exit /b 1
)

:: Also allow Python through firewall
for %%p in (python.exe python3.exe pythonw.exe) do (
  netsh advfirewall firewall add rule ^
    name="Python - EDITH" ^
    dir=in action=allow program="%LOCALAPPDATA%\Programs\Python\Python311\%%p" ^
    enable=yes >nul 2>&1
)

echo.
echo  [OK] Done! Port 8000 is now open.
echo  [OK] Now start the server: cd backend ^& python server.py
echo  [OK] Then open http://YOUR-IP:8000/setup on Magic Leap 2
echo.

:: Show current IP
echo  Your local IP addresses:
ipconfig | findstr "IPv4"

echo.
pause
