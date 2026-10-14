@echo off
cd /d "%~dp0"
py -3 tools\build_android_apk.py
if errorlevel 1 exit /b 1
echo APK tersedia di output\android\RasPBX-Android-Lab.apk
