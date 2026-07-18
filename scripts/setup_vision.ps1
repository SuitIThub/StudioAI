# Install CUDA PyTorch for JoyCaption (RTX 50xx / Blackwell needs cu128).
# Run from repo root with venv active:
#   .\scripts\setup_vision.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Missing .venv – create it first" }

Write-Host "Installing torch+cu128 (replaces CPU torch if present)..."
& $py -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu128
Write-Host "Installing vision extras..."
& $py -m pip install -e ".[vision]"
Write-Host "Verify:"
& $py -c "import torch; assert torch.cuda.is_available(), 'CUDA still missing'; print(torch.__version__, torch.cuda.get_device_name(0))"
