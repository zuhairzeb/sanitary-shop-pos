@echo off
cd /d "%~dp0\.."
set "PYTHONPATH=%CD%\.vendor"
set "TCL_LIBRARY=%CD%\.vendor\tcl\tcl8.6"
set "TK_LIBRARY=%CD%\.vendor\tcl\tk8.6"
python developer_tools\license_generator.py
