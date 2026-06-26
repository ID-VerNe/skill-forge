<#
.SYNOPSIS
    glue-engineer v4 — Setup Script (PowerShell)
.DESCRIPTION
    Copies subagent definitions and optionally installs permissions.
.PARAMETER WithPermissions
    Also install .claude/settings.json permissions.
.PARAMETER DryRun
    Show what would be done without making changes.
.EXAMPLE
    .\scripts\setup.ps1
    .\scripts\setup.ps1 -WithPermissions
    .\scripts\setup.ps1 -DryRun
#>

param(
    [switch]$WithPermissions,
    [switch]$DryRun
)

$SkillDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
$AgentsDir = Join-Path $ClaudeDir "agents"
$SettingsFile = Join-Path $ClaudeDir "settings.json"

Write-Host "=== glue-engineer v4 Setup ===" -ForegroundColor Cyan
Write-Host "  Skill directory: $SkillDir"
Write-Host ""

# Step 1: Verify the skill looks complete
Write-Host "[1/4] Validating skill structure..." -ForegroundColor Yellow
$Required = @(
    (Join-Path $SkillDir "SKILL.md"),
    (Join-Path $SkillDir "polyglot/router.py"),
    (Join-Path $SkillDir "agents/glue-repo-architect.md"),
    (Join-Path $SkillDir "agents/glue-reuse-mapper.md"),
    (Join-Path $SkillDir "agents/glue-integration-planner.md"),
    (Join-Path $SkillDir "agents/glue-synthesizer.md")
)
$Missing = 0
foreach ($f in $Required) {
    if (-not (Test-Path $f)) {
        Write-Host "  [x] Missing: $f" -ForegroundColor Red
        $Missing++
    }
}
if ($Missing -gt 0) {
    Write-Host "  [x] $Missing required file(s) missing — skill may be incomplete" -ForegroundColor Red
} else {
    Write-Host "  [v] All required files present" -ForegroundColor Green
}

# Step 2: Create agents directory
Write-Host ""
Write-Host "[2/4] Installing subagent definitions..." -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "  Would create: $AgentsDir"
    Write-Host "  Would copy: agents/*.md -> $AgentsDir/"
} else {
    New-Item -ItemType Directory -Force -Path $AgentsDir | Out-Null
    Copy-Item -Path (Join-Path $SkillDir "agents/*.md") -Destination $AgentsDir
    Write-Host "  [v] Copied agents to $AgentsDir" -ForegroundColor Green
}

# Step 3: Verify polyglot CLI
Write-Host ""
Write-Host "[3/4] Verifying polyglot CLI..." -ForegroundColor Yellow
$cliResult = & python -m polyglot --help 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [v] polyglot CLI is importable" -ForegroundColor Green
} else {
    Write-Host "  [x] polyglot CLI failed — check Python path" -ForegroundColor Red
}

# Step 4: (Optional) Install permissions
if ($WithPermissions) {
    Write-Host ""
    Write-Host "[4/4] Installing permissions..." -ForegroundColor Yellow
    if (Test-Path $SettingsFile) {
        Write-Host "  [!] $SettingsFile already exists — backing up to settings.json.bak" -ForegroundColor Yellow
        if (-not $DryRun) {
            Copy-Item -Path $SettingsFile -Destination "$SettingsFile.bak"
        }
    }
    if ($DryRun) {
        Write-Host "  Would copy: .claude/settings.json -> $SettingsFile"
    } else {
        Copy-Item -Path (Join-Path $SkillDir ".claude/settings.json") -Destination $SettingsFile
        Write-Host "  [v] Permissions installed to $SettingsFile" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "[4/4] Skipped (use -WithPermissions to install settings)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "To verify:"
Write-Host "  1. Run /agents in Claude Code — should show 4 glue-* agents"
Write-Host "  2. Run 'python -m polyglot --help' — should show deep-* commands"
Write-Host ""
Write-Host "To install permissions as well:"
Write-Host "  .\scripts\setup.ps1 -WithPermissions"