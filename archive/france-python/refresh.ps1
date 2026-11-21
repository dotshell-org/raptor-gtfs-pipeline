# Daily refresh of the live France network (python -m gtfs_bench.refresh), for the Windows
# task scheduler. Arguments are passed on: .\refresh.ps1 --force
# Java: $env:JAVA_HOME if set, else the java on PATH (any JDK 21 or later runs the pipeline).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m gtfs_bench.refresh @args
exit $LASTEXITCODE
