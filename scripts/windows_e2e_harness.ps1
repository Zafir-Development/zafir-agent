# Local harness for windows-e2e.ps1's non-GUI logic, runnable under linux
# pwsh (nix run nixpkgs#powershell). Exercises the pieces that cost CI
# round-trips when wrong: parameter surface, ref-flag probing, and the
# install/update dispatch reaching the right arm names.
param()
$ErrorActionPreference = "Stop"
$driver = Join-Path $PSScriptRoot "..\tests\install\windows-e2e.ps1"

# 1. Parse cleanly.
$tok = $null; $err = $null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $driver), [ref]$tok, [ref]$err) | Out-Null
if ($err -and $err.Count) { $err | ForEach-Object { Write-Host $_.Message }; exit 1 }
Write-Host "parse: OK"

# 2. Parameter surface: both axes present with the generator's ids. Only
# source install/update surfaces survive: the GUI installer and the packaged
# bundle routes are gone.
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $driver), [ref]$tok, [ref]$err)
$params = $ast.ParamBlock.Parameters
$byName = @{}
foreach ($p in $params) { $byName[$p.Name.VariablePath.UserPath] = $p }
foreach ($required in @("Phase", "InstallMethod", "Route", "InstallRef")) {
    if (-not $byName.ContainsKey($required)) { Write-Host "missing param: $required"; exit 1 }
}
$imSet = ($byName["InstallMethod"].Attributes | Where-Object { $_.TypeName.Name -eq "ValidateSet" }).PositionalArguments.Value
if ($imSet.Count -ne 1 -or $imSet -notcontains "installer-script") { Write-Host "InstallMethod ValidateSet must be installer-script only"; exit 1 }
$rSet = ($byName["Route"].Attributes | Where-Object { $_.TypeName.Name -eq "ValidateSet" }).PositionalArguments.Value
foreach ($m in @("hermes-desktop-app-update", "hermes-update", "installer-script")) {
    if ($rSet -notcontains $m) { Write-Host "Route ValidateSet missing $m"; exit 1 }
}
foreach ($gone in @("open-app-update", "desktop-installer@latest")) {
    if ($rSet -contains $gone) { Write-Host "Route ValidateSet still offers removed route $gone"; exit 1 }
    if ($imSet -contains $gone) { Write-Host "InstallMethod ValidateSet still offers removed method $gone"; exit 1 }
}
Write-Host "parameter surface: OK"

# 3. Dispatch bodies reference the right arms (AST-level): the install phase
# runs the source installer, the update switch keeps the three source routes.
$text = Get-Content -LiteralPath $driver -Raw
foreach ($needle in @(
    'function Invoke-PhaseInstall',
    'function Invoke-PhaseUpdate',
    'Invoke-RefInstaller $state.old "old"',
    'Invoke-HermesDesktopAppUpdate $state.current',
    'Invoke-HermesUpdate',
    'Invoke-RefInstaller $state.current "head"'
)) {
    if ($text.IndexOf($needle) -lt 0) { Write-Host "dispatch missing: $needle"; exit 1 }
}
foreach ($gone in @('Invoke-PhaseInstallGui', 'Invoke-GuiUpdateDesktopRoute', 'Assert-DesktopArtifact', 'Save-GuiDriverFailureEvidence')) {
    if ($text.IndexOf($gone) -ge 0) { Write-Host "removed GUI arm still present: $gone"; exit 1 }
}
Write-Host "dispatch arms: OK"
Write-Host "ALL HARNESS CHECKS PASSED"
