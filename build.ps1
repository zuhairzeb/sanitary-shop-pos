$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot '.vendor'
$env:TCL_LIBRARY = Join-Path $PSScriptRoot '.vendor/tcl/tcl8.6'
$env:TK_LIBRARY = Join-Path $PSScriptRoot '.vendor/tcl/tk8.6'
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; packaging stopped.' }
python -m PyInstaller --noconfirm --clean --windowed --onedir --name SanitaryShopPOS --paths .vendor --hidden-import qrcode.image.svg --add-data 'sanitary_pos/print.ps1;sanitary_pos' app.py
if ($LASTEXITCODE -ne 0) { throw 'The executable build failed.' }
Copy-Item -LiteralPath README.md -Destination dist/SanitaryShopPOS/README.md -Force
python -m PyInstaller --noconfirm --clean --windowed --onefile --name SanitaryShopPOS-Setup --add-data 'dist/SanitaryShopPOS;payload' installer.py
if ($LASTEXITCODE -ne 0) { throw 'The installer build failed.' }
