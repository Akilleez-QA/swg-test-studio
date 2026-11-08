Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
& python "$PSScriptRoot/swg-tests.py" @args
exit $LASTEXITCODE
