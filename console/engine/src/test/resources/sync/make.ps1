# Two small versions of a dataset and their packs, built by met-dataset-server's `packs` command,
# for console/engine's SyncTest: what versions/ and packs/ beside this script hold. Needs the
# met-dataset-server checkout; writes into $out (then copy versions/ and packs/ here).
param(
    [string]$out = "$env:TEMP\sync-fixtures",
    [string]$server = (Join-Path (Resolve-Path "$PSScriptRoot\..\..\..\..\..\..").Path "..\met-dataset-server")
)
$ErrorActionPreference = "Stop"
$v1 = "20261120-00000001"; $v2 = "20261121-00000002"
Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Write-Records([string]$path, [int]$count, [int]$seed, [int[]]$changed) {
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $count; $i++) {
        $value = ($i * 7919 + $seed) % 1000
        if ($changed -contains $i) { $value = $value + 1 }
        [void]$sb.Append("stop $i;name $($i % 97);lat 45.$value;lon 4.$($i % 13)`n")
    }
    New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
    [System.IO.File]::WriteAllText($path, $sb.ToString(), $utf8)
}

foreach ($v in @($v1, $v2)) {
    $dir = "$out\versions\$v"
    $edits = if ($v -eq $v2) { @(10, 400, 401, 900) } else { @() }
    Write-Records "$dir\semaine\stops.bin" 1200 1 $edits
    Write-Records "$dir\samedi\stops.bin" 800 2 @()
    [System.IO.File]::WriteAllText("$dir\dataset.json", "{""version"":""$v""}`n", $utf8)
}

$env:JAVA_HOME = "$env:USERPROFILE\.gradle\jdks\eclipse_adoptium-21-amd64-windows.2"
Push-Location $server
try {
    & .\gradlew.bat -q franceLive "--args=packs --from $out\versions\$v1 --to $out\versions\$v1 --out $out\packs\$v1"
    & .\gradlew.bat -q franceLive "--args=packs --from $out\versions\$v1 --to $out\versions\$v2 --out $out\packs\$v2"
} finally { Pop-Location }
# v1's pack from itself is of no use.
Remove-Item "$out\packs\$v1\from-$v1.pack" -ErrorAction SilentlyContinue
Get-ChildItem -Recurse $out -File | ForEach-Object { "{0,8} {1}" -f $_.Length, $_.FullName.Substring($out.Length + 1) }
