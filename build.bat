@echo off
echo Building JobHunter-AI Executable...
pyinstaller --noconfirm --onedir --windowed --add-data "templates;templates/" --add-data "static;static/"  "app.py"
echo Build Complete!
pause
