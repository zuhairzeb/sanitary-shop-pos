$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
# Build runs the complete test suite before packaging the current source.
& .\build.ps1
python developer_tools/publish_update.py --publish
if ($LASTEXITCODE -ne 0) { throw 'Publishing failed. See the error above.' }
