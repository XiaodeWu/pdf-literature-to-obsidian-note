#Requires -Version 5.1
<#
.SYNOPSIS
    Install the pdf-literature-to-obsidian-note skill.
.DESCRIPTION
    Copies SKILL.md + scripts/ + verify.py into an agent skills directory
    (default: %USERPROFILE%\.workbuddy\skills\pdf-literature-to-obsidian-note)
    and installs Python dependencies.
    NOTE: console output is ASCII only on purpose (PS 5.1 + UTF-8 no-BOM issue).
.PARAMETER Target
    Destination skill directory.
.PARAMETER SkipDeps
    Do not run pip install.
.PARAMETER Python
    Python interpreter to use (default: auto-detect python on PATH).
.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -Target "$env:APPDATA\some-agent\skills\pdf-note" -SkipDeps
#>
param(
    [string]$Target = (Join-Path $env:USERPROFILE ".workbuddy\skills\pdf-literature-to-obsidian-note"),
    [switch]$SkipDeps,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Src = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== pdf-literature-to-obsidian-note installer ==" -ForegroundColor Cyan
Write-Host "Source: $Src"
Write-Host "Target: $Target"
Write-Host ""

foreach ($f in @("SKILL.md", "scripts\extract_pages.py", "requirements.txt", "verify.py")) {
    if (-not (Test-Path (Join-Path $Src $f))) {
        Write-Host "[FAIL] missing file: $f" -ForegroundColor Red
        exit 1
    }
}

if (Test-Path $Target) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$Target.bak-$stamp"
    Copy-Item -Path $Target -Destination $backup -Recurse -Force
    Write-Host "[i] existing install backed up to:" -ForegroundColor Yellow
    Write-Host "    $backup"
}

New-Item -ItemType Directory -Path (Join-Path $Target "scripts") -Force | Out-Null
Copy-Item (Join-Path $Src "SKILL.md")          (Join-Path $Target "SKILL.md") -Force
Copy-Item (Join-Path $Src "requirements.txt")  (Join-Path $Target "requirements.txt") -Force
Copy-Item (Join-Path $Src "verify.py")         (Join-Path $Target "verify.py") -Force
Copy-Item (Join-Path $Src "scripts\extract_pages.py") (Join-Path $Target "scripts\extract_pages.py") -Force
Copy-Item (Join-Path $Src "README.md")         (Join-Path $Target "README.md") -Force -ErrorAction SilentlyContinue
Write-Host "[OK] files copied" -ForegroundColor Green

if ($SkipDeps) {
    Write-Host "[i] -SkipDeps set, dependencies not installed" -ForegroundColor Yellow
} else {
    if (-not $Python) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source } else { $Python = "python" }
    }
    Write-Host ""
    Write-Host "[i] using interpreter: $Python"
    & $Python -c "import sys; print('    ' + sys.executable)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] python not runnable: $Python" -ForegroundColor Red
        exit 1
    }
    Write-Host "[i] installing dependencies (pymupdf4llm, pymupdf, pdfplumber, pypdfium2) ..."
    & $Python -m pip install -r (Join-Path $Src "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] pip install failed. Try a mirror: -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] dependencies installed" -ForegroundColor Green

    Write-Host ""
    Write-Host "[i] running self-check ..."
    & $Python (Join-Path $Src "verify.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] self-check reported failures, see output above" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "== done ==" -ForegroundColor Cyan
Write-Host "Next steps:"
Write-Host "  1. Edit SKILL.md and replace <VAULT> / <PDF_LIB> / <SKILL_DIR> with your own paths."
Write-Host "  2. Restart your agent so the skill gets picked up."
Write-Host "  3. Try a 20-30 page PDF first."
