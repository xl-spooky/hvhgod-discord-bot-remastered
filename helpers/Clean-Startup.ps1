#!/usr/bin/env pwsh

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$PSNativeCommandUseErrorActionPreference = $true

# Go to the script path and go to ..
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptPath

if (-not (Test-Path -Path "$root/.env")) {
    Write-Error "You must first create a .env file in the root of the project."
    exit 1
}

Set-Location $root

Write-Progress -Activity "[TEST] Clean Startup" -Status "Shutdown containers" -PercentComplete 0
docker compose down

# remove data directory

# if there is a argument -EraseData
if ($args -contains "-EraseData") {
    Write-Progress -Activity "[TEST] Clean Startup" -Status "Removing data" -PercentComplete 20
    Remove-Item -Path data -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Progress -Activity "[TEST] Clean Startup" -Status "Starting Database" -PercentComplete 75
docker compose up -d db

Write-Progress -Activity "[TEST] Clean Startup" -Status "Starting bot" -PercentComplete 99
Start-Sleep -Seconds 2
docker compose up bot
