# Free StudioPoseBridge port when Windows left a ghost LISTEN socket
# (netstat shows a PID that no longer exists).
#
# Run elevated (right-click -> Run as administrator), then restart Studio.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\free-bridge-port.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\free-bridge-port.ps1 -Port 7842

param(
    [int]$Port = 7842
)

function Show-Port {
    param([int]$P)
    netstat -ano | findstr ":$P"
}

Write-Host "Port $Port before:"
Show-Port -P $Port
if (-not (netstat -ano | findstr ":$Port")) {
    Write-Host "Already free."
    exit 0
}

$owner = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty OwningProcess)
if ($owner) {
    $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Live process holds the port: PID $owner ($($proc.ProcessName))"
        Write-Host "Close Studio / kill that process first, then re-run if needed."
        exit 1
    }
    Write-Host "Ghost LISTEN: PID $owner is gone. Restarting WinNAT to drop orphaned sockets..."
}

# Known fix for orphaned LISTEN entries without a full reboot.
# Requires Administrator.
$ErrorActionPreference = "Stop"
try {
    net stop winnat
    Start-Sleep -Seconds 2
    net start winnat
}
catch {
    Write-Host "FAILED: $($_.Exception.Message)"
    Write-Host "Open an elevated PowerShell and run:"
    Write-Host "  net stop winnat && net start winnat"
    exit 1
}

Start-Sleep -Seconds 1
Write-Host "Port $Port after:"
Show-Port -P $Port
if (netstat -ano | findstr ":$Port") {
    Write-Host "Still blocked. Last resort without reboot: change Bridge Port in"
    Write-Host "  BepInEx/config/com.suitji.studio_pose_bridge.cfg"
    Write-Host "and matching bridge.url in deploy/config.main-pc.yaml"
    exit 2
}

Write-Host "PORT FREE - restart Studio so the plugin can bind again."
exit 0
