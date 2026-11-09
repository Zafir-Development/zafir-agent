# Journey-owned mock provider for the source install/update drivers.
# Dot-sourced by tests/install/windows-e2e.ps1; no desktop driver remains.
# Callers supply a checkout-provisioned Node; never resolve tooling from OLD.
function Start-DesktopJourneyMock([string]$Node, [string]$Assets, [string]$Work, [string]$HermesHome, [string]$Out) {
    New-Item -ItemType Directory -Path $Out -Force | Out-Null
    $urlFile = Join-Path $Work 'chat-mock-url'
    # An earlier step's mock died with that step; the detached gateway did not, and it
    # kept the provider URL it read at boot. Rebind that URL's port (see mock-provider.mjs).
    $priorUrl = if (Test-Path -LiteralPath $urlFile) { (Get-Content -LiteralPath $urlFile -Raw).Trim() } else { '' }
    Remove-Item -LiteralPath $urlFile -Force -ErrorAction SilentlyContinue
    $mockArgs = @(('"' + (Join-Path $Assets 'mock-provider.mjs') + '"'), ('"' + $urlFile + '"'))
    if ($priorUrl) { $mockArgs += ('"' + $priorUrl + '"') }
    $mock = Start-Process -FilePath $Node -ArgumentList $mockArgs `
        -PassThru -RedirectStandardOutput (Join-Path $Out 'chat-mock.log') -RedirectStandardError (Join-Path $Out 'chat-mock-error.log')
    try {
        $deadline = (Get-Date).AddSeconds(30)
        while (-not (Test-Path -LiteralPath $urlFile)) {
            if ($mock.HasExited -or (Get-Date) -ge $deadline) { throw 'Desktop mock did not become ready' }
            Start-Sleep -Milliseconds 200
        }
        $env:HERMES_E2E_MOCK_URL = (Get-Content -LiteralPath $urlFile -Raw).Trim()
        Invoke-RestMethod -Uri "$env:HERMES_E2E_MOCK_URL/__e2e__/prompts" -TimeoutSec 5 | Out-Null
        $configWriter = [IO.Path]::GetFullPath((Join-Path $Assets '..\..\..\tests-js\scripts\mock-provider-config.ts'))
        & $Node $configWriter $HermesHome $env:HERMES_E2E_MOCK_URL
        if ($LASTEXITCODE -ne 0) { throw 'Desktop mock configuration failed' }
        return $mock
    } catch {
        if (-not $mock.HasExited) { Stop-Process -Id $mock.Id -ErrorAction SilentlyContinue }
        throw
    }
}
