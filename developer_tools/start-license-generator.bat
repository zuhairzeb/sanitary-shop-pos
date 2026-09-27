@echo off
setlocal
cd /d "%~dp0\.."
set "PYTHONPATH=%CD%\.vendor"
set "TCL_LIBRARY=%CD%\.vendor\tcl\tcl8.6"
set "TK_LIBRARY=%CD%\.vendor\tcl\tk8.6"
python developer_tools\license_generator.py %*
if errorlevel 1 (
    echo.
    echo License generator could not start or generate the license. See the error above.
    pause
    exit /b 1
)
