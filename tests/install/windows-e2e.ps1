# ============================================================================
# Windows source install + update E2E driver (the REAL user flow)
# ============================================================================
# Proves, on a real Windows machine, that a user who installs Hermes from the
# source installer can then update to the commit under test through a real
# update surface:
#
#   INSTALL   - runs the ref's own scripts/install.ps1 headless (the irm | iex
#               one-liner, without the network hop). The installed source
#               checkout must land on OLD (-InstallRef, default: the newest
#               release tag) -- the version a user who installed on release
#               day is on -- against serve.git, whose `main` is parked there.
#   UPDATE    - OLD -> HEAD through the route selected by -Route:
#                 hermes-desktop-app-update
#                            launch the app via `hermes desktop` (the source
#                            desktop launch surface; it stays until the
#                            desktop app is removed), intercept the product's
#                            final spawn, and CLICK Settings -> About ->
#                            "Update now" under Playwright. The production
#                            hand-off chain runs untouched: marker, app quit,
#                            detached updater, `hermes update`, desktop
#                            rebuild, RELAUNCH.
#                 hermes-update
#                            run `hermes update` from the installed command
#                            (the CLI route a user might take).
#                 installer-script
#                            re-run the source installer over the existing
#                            install (a user re-running the one-liner).
#               Every route asserts target sha, marker cleanup, result JSON
#               (when the updater wrote one), working hermes, and preserved
#               user/plugin state.
#
# HOW THE STAGING WORKS (no MITM proxy, no network fakery):
#   We bare-clone the checkout into <workroot>\serve.git and point every git
#   process at it with url.<file-url>.insteadOf rewrites for the two
#   canonical repo URLs, via a driver-owned gitconfig selected with
#   GIT_CONFIG_GLOBAL. (NOT GIT_CONFIG_COUNT/KEY_n/VALUE_n env config --
#   install.ps1 sets those itself and silently clobbers them.) The
#   installer's `git clone` and `hermes update`'s `git fetch origin`
#   transparently hit OUR bare repo. Its `main` serves OLD for the install
#   phase; the update phase advances it to HEAD -- an update becomes
#   available exactly the way it does for a real user. Installer and
#   updater run byte-for-byte as shipped; everything else (uv, PyPI, npm,
#   the installer's raw.githubusercontent install.ps1 download) uses the
#   real network, same as a user install.
#
# PROOF: screenshots at every renderer step (Playwright), the app's update
# window transcript, and the hand-off log. All uploaded as CI artifacts.
#
# DEVIATIONS FROM PRODUCTION (each one deliberate and small):
#   * the git URL redirect itself
#   * serve.git gets uploadpack.allowAnySHA1InWant=true so the installer's
#     baked -Commit pin can be fetched from the redirected clone the same
#     way GitHub's upload-pack allows it.
#   * A dummy provider key is seeded after install so the update leg sees
#     the ready app shell instead of the onboarding overlay (a real
#     updating user has a configured provider).
#   * The git shim reports the official URL. Detached updaters can resolve a
#     different git.exe, so the test home also records that upstream setup was
#     declined. The file:// transport must not prompt to add a second remote.
#
# USAGE (local Windows box or CI):
#   powershell -File tests\install\windows-e2e.ps1 -Phase all
#   ... -Phase stage / install / update / verify-stamp
#   Phases share state via <workroot>\shas.json, so CI can run them as
#   separate steps for readable logs. -Route selects the update surface; the
#   install phase always installs from the source script, and install writes
#   what update needs (paths, how OLD landed) into the shared state.
# ============================================================================

param(
    [ValidateSet("stage", "install", "update", "verify-stamp", "all")]
    [string]$Phase = "all",

    # How OLD gets installed, named by the same ids the combination
    # generator (scripts/sandbox/generate-e2e-matrix.mjs) declares. Only the
    # source installer remains.
    [ValidateSet("installer-script")]
    [string]$InstallMethod = "installer-script",

    # Update method to exercise in the update phase, same id namespace.
    [ValidateSet("hermes-desktop-app-update", "hermes-update", "installer-script")]
    [string]$Route = "hermes-update",

    # The OLD version: the ref served as `main` while the installer runs,
    # i.e. what the user starts on. The source installer installs whatever
    # `main` points at, so staging OLD means serving it there.
    # Empty or "auto" = newest release tag in the checkout (the "user on
    # the current release" starting point, same philosophy as the linux
    # axis's tag matrix). "auto" exists because `powershell -File` silently
    # swallows an empty-string argument ('Missing an argument for
    # parameter'), so the workflow cannot pass "".
    [string]$InstallRef = "auto",
    # Update target ref (default HEAD). A stable-to-stable leg passes the
    # next release tag here; only label the leg stable-to-stable when BOTH
    # refs are release tags. NEXT mints a synthetic child of -InstallRef
    # (the HEAD -> NEXT leg: install HEAD, update with HEAD's own updater).
    [string]$UpdateRef = "HEAD",

    # Repo checkout whose HEAD is the update target.
    [string]$RepoRoot = "",

    [string]$WorkRoot = $(if ($env:HERMES_E2E_WORKROOT) { $env:HERMES_E2E_WORKROOT } else { Join-Path $env:TEMP "hermes-source-gui-e2e" }),

    # Driver dependencies come from the current checkout lockfile.
    [string]$DriverNode = $env:HERMES_E2E_NODE
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
# Match an interactive Unicode console when Python output is piped into the
# UTF-8 transcript. Old releases otherwise select cp1252 and crash on banners.
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = [Console]::OutputEncoding

# One PM tool store per leg. setup-pm exports HERMES_RUNTIME_DIR (its own
# store) and HERMES_PYTHON for this job's tooling. A user's machine has one
# store, <HERMES_HOME>\tools, and the desktop smoke already launches the app
# that way (smoke-env.mjs drops every HERMES_* override). When install.ps1
# and `hermes update` saw the job's store while the smoke did not, a leg
# settled onto two stores and the update rewrote its own running launcher
# ("source launcher publication failed"). No product step (installer, app,
# update, chat) sees the job's variables; the driver keeps setup-pm only
# through $DriverPython. PATH keeps setup-pm's tools, as older installers
# expect uv/ripgrep there.
$DriverPython = if ($env:HERMES_PYTHON) { $env:HERMES_PYTHON } else { (Get-Command python.exe -ErrorAction Stop).Source }
foreach ($jobOnly in @('HERMES_RUNTIME_DIR', 'HERMES_PYTHON', 'VIRTUAL_ENV')) {
    if (Test-Path -LiteralPath "env:$jobOnly") { Remove-Item -LiteralPath "env:$jobOnly" }
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
# The workflow's HERMES_E2E_WORKROOT is "<workspace>\..\hermes-source-gui-e2e".
# Everything below derives HERMES_HOME (and so the PM store) from it, and a
# user's HERMES_HOME has no ".." segment. With one, Windows reports the store
# Python's sys.executable normalized while PM names it with the "..", and
# prepare_launch() relaunched into the same interpreter forever (#122513).
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)

$ServeRepo   = Join-Path $WorkRoot "serve.git"
$HermesHome  = Join-Path $WorkRoot "hermes-home"
$InstallDir  = Join-Path $HermesHome "hermes-agent"
$StatePath   = Join-Path $WorkRoot "shas.json"
$ProofRoot   = Join-Path $WorkRoot "proof"
$AssetsDir   = Join-Path $PSScriptRoot "e2e-assets"
if (-not $DriverNode) { $DriverNode = (Get-Command node.exe -ErrorAction Stop).Source }
$env:HERMES_E2E_NODE = $DriverNode
$env:HERMES_DESKTOP_USER_DATA_DIR = Join-Path $WorkRoot 'electron-user-data'
$script:ChatMock = $null
$script:ChatFailure = $false
. (Join-Path $AssetsDir 'desktop-smoke-windows.ps1')

function Start-JourneyChat {
    if (-not $script:ChatMock) {
        $script:ChatFailure = $true
        $script:ChatMock = Start-DesktopJourneyMock $DriverNode $AssetsDir $WorkRoot $HermesHome $ProofRoot
        $script:ChatFailure = $false
    }
}

function Invoke-DesktopCheckpoint([string]$ChatPhase, [string]$Commit, [string]$Method) {
    # Every checkpoint chats through the journey mock. Without it the smoke starts a private mock,
    # and the detached gateway that checkpoint leaves running keeps that dead URL into later steps;
    # the journey mock's URL file lets a later step's mock rebind the same port.
    Start-JourneyChat
    $script:ChatFailure = $true
    # The app must be able to detach its gateway, as from a user's launch (see Invoke-OutsideRunnerJob).
    $chatExit = Invoke-OutsideRunnerJob "desktop-$ChatPhase" $WorkRoot $DriverNode @(
        (Join-Path $AssetsDir 'source-desktop-smoke.mjs'),
        '--root', $InstallDir, '--home', $HermesHome, '--user-data', $env:HERMES_DESKTOP_USER_DATA_DIR,
        '--out', $ProofRoot, '--phase', $ChatPhase, '--expect-commit', $Commit, '--desktop', $script:ExpectedDesktop, '--method', $Method)
    if ($chatExit -ne 0) { throw "Mandatory desktop chat $ChatPhase failed (exit $chatExit)" }
    $script:ChatFailure = $false
}

function Confirm-OldChat([string]$Out) {
    $receipt = Get-Content -LiteralPath (Join-Path $Out 'desktop-chat-old.json') -Raw | ConvertFrom-Json
    if ($receipt.status -ne 'passed') { throw 'Mandatory OLD update-window chat failed' }
    $script:ChatFailure = $false
}

$RepoUrlHttps = "https://github.com/NousResearch/hermes-agent.git"
$RepoUrlSsh   = "git@github.com:NousResearch/hermes-agent.git"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("=" * 74)
    Write-Host "== $Message"
    Write-Host ("=" * 74)
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw "E2E ASSERTION FAILED: $Message"
    }
    Write-Host "  [ok] $Message"
}

function Invoke-Git([string[]]$GitArgs) {
    # PS 5.1 trap: under $ErrorActionPreference = "Stop", a native command
    # that writes ANYTHING to stderr while merged via 2>&1 throws a
    # NativeCommandError even when it exits 0 (git loves stderr for
    # progress/notices). Relax EAP around the native call only; exit-code
    # checking below is the real error gate.
    #
    # ALWAYS the real git.exe, never the shim we ship.
    # annoying bug where .bat files eat ^ args.
    # if hermes ever adds a git command that calls something with ^ this will break, lol.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $script:RealGitExe @GitArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "git $($GitArgs -join ' ') failed (exit $LASTEXITCODE): $output"
        }
        return ($output | Out-String).Trim()
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Set-GitRedirect {
    # we redirect to our own repo so we can play around with what commit hermes thinks we're on.
    # MECHANISM: a driver-owned global gitconfig selected via
    # GIT_CONFIG_GLOBAL. Do NOT use GIT_CONFIG_COUNT/KEY_n/VALUE_n env
    # config here -- install.ps1 SETS those itself (GIT_CONFIG_COUNT=1,
    # windows.appendAtomically), silently clobbering any redirect we put
    # there. install.ps1's own `git config --global` writes simply land in
    # our file, so its compat settings still apply. Nothing leaks onto the
    # machine: the file lives in the workroot and dies with it.
    $fileUrl = "file:///" + ($ServeRepo -replace "\\", "/")
    $gitCfg = Join-Path $WorkRoot "e2e-gitconfig"
    if (-not (Test-Path -LiteralPath $WorkRoot)) {
        New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null
    }
    # first, get the set origin url
    $actualGitUrl = Invoke-Git @("-C", $RepoRoot, "remote", "get-url", "origin")
    # then override it
    @"
[url "$fileUrl"]
	insteadOf = $actualGitUrl
    insteadOf = $RepoUrlHttps
    insteadOf = $RepoUrlSsh
"@ | Set-Content -LiteralPath $gitCfg -Encoding ASCII
    $env:GIT_CONFIG_GLOBAL = $gitCfg
    # serve.git publishes commits on main, not releases: HEAD's installer would otherwise
    # install the latest stable release its tags name. Older installers ignore the variable.
    $env:HERMES_INSTALL_CHANNEL = 'main'

    # check it worked
    $actualGitUrl = Invoke-Git @("-C", $RepoRoot, "remote", "get-url", "origin")
    Assert-True ($actualGitUrl -eq $fileUrl) "git URL redirect: origin resolves to '$actualGitUrl', expected '$fileUrl'."
    Write-Host "  git URL redirect via GIT_CONFIG_GLOBAL=$gitCfg"
    Write-Host "    $RepoUrlHttps -> $fileUrl"

    # shim git and make 'git remote get-url origin' report the actual HA upstream

    # insteadOf is transparent for transport but `git remote get-url origin` gives you the
    # replacement, so _get_origin_url() sees file://$SERVE_REPO and _is_fork() would return true.
    # we check for the arguments "remote get-url origin" in order in any position
    # to allow for e.g. -c with some config being passed.
    # if we didn't do this, we'd need the  .skip_upstream_prompt file to prevent a hang in headless,"add the
    # official repo as upstream?" prompt would hang a headless run. But we don't anymore :D

    # The dispatch-time capture, not PATH: a fresh-machine leg has already
    # stripped git from PATH by the time stage re-arms the redirect.
    $realGit = $script:RealGitExe
        # Export the real git so later checks can observe the TRANSPORT url. Once
        # the shim below is on PATH, `git` reports the official origin for
        # `remote get-url origin` (so fork detection sees it); any check that must
        # see the file:// redirect instead has to bypass the shim via this path.
        $env:HERMES_E2E_REAL_GIT = $realGit

    if ($script:FreshMachine) {
        # A fresh Windows box has no git. install.ps1's Get-PinnedGit returns
        # ANY git on PATH (the dev shortcut), so the runner's git -- or the
        # shim below -- would skip pinned-git staging entirely. Take every
        # git.exe directory off PATH and install no shim: the product must
        # provision its own. The shim's one job (fork detection seeing the
        # official origin) is covered by .skip_upstream_prompt, same as
        # routes whose detached updater bypasses the shim.
        $kept = @($env:PATH -split ';' | Where-Object { $_ -and -not (Test-Path -LiteralPath (Join-Path $_ 'git.exe')) })
        $env:PATH = $kept -join ';'
        Assert-True (-not (Get-Command git -ErrorAction SilentlyContinue)) "fresh machine: no git resolvable on PATH"
        Write-Host "  fresh machine: git removed from PATH, no remote get-url shim"
        return
    }
        $shimDir = Join-Path $WorkRoot "shim"
    New-Item -ItemType Directory -Path $shimDir -Force | Out-Null
    $shimPath = Join-Path $shimDir "git.bat"
    @"
@echo off
setlocal enabledelayedexpansion
set prev2=
set prev1=
:loop
if "%~1"=="" goto passthrough
if /I "!prev2!"=="remote" if /I "!prev1!"=="get-url" if /I "%~1"=="origin" (
    echo $RepoUrlHttps
    exit /b 0
)
set prev2=!prev1!
set prev1=%~1
shift
goto loop
:passthrough
`"$realGit`" %*
exit /b %ERRORLEVEL%
"@ | Set-Content -LiteralPath $shimPath -Encoding ASCII

    $env:PATH = "$shimDir;$env:PATH"

    # Check it worked THROUGH the shim - deliberately not Invoke-Git, which
    # pins the real git.exe. `git` via PATH here is exactly how the
    # product's callers resolve it. Probe the intercepted verb AND plain
    # passthrough.
    #
    # KNOWN HOLE, accepted: cmd parses the command line before the bat sees
    # %*, and callers only quote args containing whitespace (PowerShell
    # native binding and python's list2cmdline alike) - so a caret arg like
    # rev-parse HEAD^{commit} loses its caret THROUGH ANY .bat, unfixably.
    # A .ps1 shim would dodge cmd but PATHEXT-resolving callers (python -
    # the shim's entire audience) never see .ps1 files, so .bat it stays.
    # The driver's own git plumbing therefore pins git.exe (Invoke-Git),
    # and the product's shimmed flows (fork detection: remote get-url) use
    # no caret revs. If a product path ever sends carets through the shim,
    # the leg fails loudly on a bad-revision error naming the mangled arg.
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $observedGitUrl = (& git -C $RepoRoot remote get-url origin 2>&1 | Out-String).Trim()
    $passthroughProbe = (& git -C $RepoRoot rev-parse HEAD 2>&1 | Out-String).Trim()
    $passthroughExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    Assert-True ($observedGitUrl -eq $RepoUrlHttps) "git remote get-url shim: origin resolves to '$observedGitUrl', expected '$RepoUrlHttps'"
    Assert-True ($passthroughExit -eq 0 -and $passthroughProbe -match '^[0-9a-f]{40}$') "shim passthrough works: rev-parse HEAD -> '$passthroughProbe'"
    Write-Host "  git remote get-url shim: $shimPath -> $realGit"
    Write-Host "    'remote get-url origin' now reports $RepoUrlHttps"
}

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        throw "State file not found: $StatePath -- run '-Phase stage' first."
    }
    return Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
}

function Get-InstalledHead {
    return Invoke-Git @("-C", $InstallDir, "rev-parse", "HEAD")
}

function Get-DesktopExe {
    foreach ($c in @(
        (Join-Path $InstallDir "apps\desktop\release\win-unpacked\Hermes.exe"),
        (Join-Path $InstallDir "apps\desktop\release\win-arm64-unpacked\Hermes.exe")
    )) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    return $null
}

# Install-side state snapshot, taken BEFORE Test-HermesRuns can throw: on
# app-update legs the updater runs detached and its transcript lands in the
# product logs and hand-off files, not in this driver. Copy those plus the
# venv entry-point dir while the install is still there to inspect, so a
# failed post-update assertion leaves its evidence in the proof tree.
function Save-InstallSideState([string]$Label) {
    $dest = Join-Path $ProofRoot "install-side-$Label"
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    $logsDir = Join-Path $HermesHome "logs"
    if (Test-Path -LiteralPath $logsDir) {
        Copy-Item $logsDir (Join-Path $dest "hermes-logs") -Recurse -Force -ErrorAction SilentlyContinue
    }
    $resultFile = Join-Path $HermesHome ".hermes-update-result.json"
    if (Test-Path -LiteralPath $resultFile) {
        Copy-Item $resultFile $dest -Force -ErrorAction SilentlyContinue
    }
    $venvScripts = Join-Path $InstallDir "venv\Scripts"
    if (Test-Path -LiteralPath $venvScripts) {
        Get-ChildItem -LiteralPath $venvScripts |
            Select-Object Name, Length, LastWriteTime |
            Format-Table -AutoSize | Out-String |
            Set-Content (Join-Path $dest "venv-scripts-ls.txt")
    }
    Get-ChildItem -LiteralPath $HermesHome -ErrorAction SilentlyContinue |
        Select-Object Name, Length, LastWriteTime |
        Format-Table -AutoSize | Out-String |
        Set-Content (Join-Path $dest "hermes-home-ls.txt")
}

function Test-HermesRuns([string]$Label) {
    Save-InstallSideState $Label
    $hermesExe = $null
    try {
        $hermesExe = Get-SourceHermes $InstallDir
    } catch {
        # A pre-handoff release cannot complete inside `hermes update`: its
        # update path reaches no retired-hook seam, so the update ends with the
        # tree at HEAD and no published launcher. The NEXT ordinary startup
        # completes it (hermes_bootstrap -> prepare_launch -> sync PM, publish
        # launchers, re-exec). Drive that startup here, WITHOUT the lazy-install
        # ban, and only when the launcher is missing -- so a healthy update is
        # still judged by the strict checks below, and `--version` probes keep
        # their ban: a probe must never complete an unfinished update.
        Write-Host "  no published launcher yet; running the next ordinary startup (this is what completes a pre-handoff release)"
        $startupHermes = Get-SourceHermesForStartup $InstallDir
        $startupLog = Join-Path $WorkRoot 'logs\post-update-startup.log'
        New-Item -ItemType Directory -Force -Path (Split-Path $startupLog) | Out-Null
        # prepare_launch reports its progress on stderr, and a native command's
        # stderr becomes a terminating NativeCommandError under the wrong
        # preference -- which killed this step before the heal could finish.
        # Same idiom the --version probe below already uses.
        $prevStartupEap = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $startupHermes status 2>&1 | Out-File -Encoding UTF8 $startupLog
            $startupExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevStartupEap
        }
        Write-Host "  first startup after the update ran (exit $startupExit); the checks below assert the launcher it must have published"
        $hermesExe = Get-SourceHermes $InstallDir
    }
    & $DriverPython -B (Join-Path $AssetsDir 'source_driver.py') --root $InstallDir --launcher $hermesExe --desktop $script:ExpectedDesktop
    Assert-True ($LASTEXITCODE -eq 0) "$Label -- read-only install verification (no repair)"
    $prevLazy = $env:HERMES_DISABLE_LAZY_INSTALLS
    $prevBytecode = $env:PYTHONDONTWRITEBYTECODE
    $prevEap = $ErrorActionPreference
    try {
        $env:HERMES_DISABLE_LAZY_INSTALLS = '1'
        $env:PYTHONDONTWRITEBYTECODE = '1'
        $ErrorActionPreference = 'Continue'
        & $hermesExe --version 2>&1 | ForEach-Object { Write-Host "    hermes --version| $_" }
        $versionExit = $LASTEXITCODE
    } finally {
        $env:HERMES_DISABLE_LAZY_INSTALLS = $prevLazy
        $env:PYTHONDONTWRITEBYTECODE = $prevBytecode
        $ErrorActionPreference = $prevEap
    }
    Assert-True ($versionExit -eq 0) "$Label -- hermes --version exits 0"
}

# ----------------------------------------------------------------------------
# Script-install arm: the irm | iex one-liner, headless (the install.ps1
# shipped AT the ref under test, run with flags probed from that ref's own
# script text - older releases reject parameters added later).
# ----------------------------------------------------------------------------
# shellcheck source=../e2e-assets/ts-prefix.ps1
. (Join-Path $PSScriptRoot "e2e-assets\ts-prefix.ps1")
. (Join-Path $PSScriptRoot "e2e-assets\source-driver.ps1")
. (Join-Path $AssetsDir 'source-build-env.ps1')

function Write-LogGroup([string]$Title, [string]$LogPath) {
    Write-Host "::group::$Title"
    if (Test-Path -LiteralPath $LogPath) { Get-Content -LiteralPath $LogPath | Write-Host }
    Write-Host "::endgroup::"
}

function Invoke-RefInstaller {
    param([string]$Ref, [string]$Label)
    $script = Join-Path $WorkRoot "install-$Label.ps1"
    (Invoke-Git @("-C", $RepoRoot, "show", "$Ref`:scripts/install.ps1")) -join "`n" |
        Set-Content -LiteralPath $script -Encoding UTF8
    $flags = @("-HermesHome", $HermesHome, "-InstallDir", $InstallDir)
    $text = Get-Content -LiteralPath $script -Raw
    if ($text -match '\$NonInteractive') { $flags += "-NonInteractive" }
    else { $flags += "-SkipSetup" }
    New-Item -ItemType Directory -Path (Join-Path $WorkRoot "logs") -Force | Out-Null
    $log = Join-Path $WorkRoot "logs\install-$Label.log"
    # uv reads the CURRENT DIRECTORY's project metadata. Run from inside this
    # checkout and every interpreter probe in a ref's installer is resolved
    # against HEAD's requires-python (3.14), so it refuses the version that ref
    # pins and the install fails. A user runs the script from their own
    # directory, so give it one that is not a project.
    $runDir = Join-Path $WorkRoot "install-cwd"
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    $hangLog = Join-Path $WorkRoot "logs\install-$Label-hang-processes.txt"
    $watchdog = Start-HangWatchdog -Minutes $InstallDeadlineMinutes -EvidencePath $hangLog
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    Push-Location $runDir
    try {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $script @flags 2>&1 | Add-TsPrefix | Out-File -Encoding UTF8 $log
        $installExit = $LASTEXITCODE
    } finally {
        Pop-Location
        Stop-HangWatchdog $watchdog
    }
    $ErrorActionPreference = $prevEap
    Write-LogGroup "install.ps1 ($Label) transcript" $log
    if (Test-Path -LiteralPath $hangLog) {
        Write-LogGroup "install.ps1 ($Label) hang evidence (process table, Python stacks)" $hangLog
        throw "E2E ASSERTION FAILED: install.ps1 ($Label) was still running after $InstallDeadlineMinutes minutes; the process table and stacks above show where"
    }
    Assert-True ($installExit -eq 0) "install.ps1 ($Label) exited 0"
}

function Invoke-HermesUpdate {
    # --yes reaches the update subcommand only in later
    # releases; ask the installed binary, never parse its source.
    $hermesExe = Get-SourceHermes $InstallDir
    $updateArgs = @("update")
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $helpText = & $hermesExe update --help 2>&1 | Out-String
    $helpExit = $LASTEXITCODE
    if ($helpExit -ne 0) {
        $ErrorActionPreference = $prevEap
        throw "Installed update --help failed: $helpText"
    }
    if ($helpText -match '--yes') { $updateArgs += "--yes" }
    New-Item -ItemType Directory -Path (Join-Path $WorkRoot "logs") -Force | Out-Null
    $log = Join-Path $WorkRoot "logs\update.log"
    $hangLog = Join-Path $WorkRoot "logs\update-hang-processes.txt"
    $watchdog = Start-HangWatchdog -Minutes $UpdateDeadlineMinutes -EvidencePath $hangLog
    Push-Location $InstallDir
    try {
        & $hermesExe @updateArgs 2>&1 | Add-TsPrefix | Out-File -Encoding UTF8 $log
        $updateExit = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prevEap
        Stop-HangWatchdog $watchdog
    }
    Write-LogGroup "hermes update transcript" $log
    if (Test-Path -LiteralPath $hangLog) {
        Write-LogGroup "hermes update hang evidence (process table, Python stacks)" $hangLog
        throw "E2E ASSERTION FAILED: hermes update was still running after $UpdateDeadlineMinutes minutes (its output pipe never closed); the process table above shows which process held it"
    }
    Assert-True ($updateExit -eq 0) "hermes update exited $updateExit (expected 0)"
}

# install.ps1 and `hermes update` normally finish in
# under 25 minutes. Past these deadlines the watchdog records every process
# (pid, parent, start time, command line) plus a py-spy stack of each Python
# process, then stops this leg's processes, so a hang fails with evidence --
# whether the product itself is stuck or a detached child still holds its
# output pipe -- instead of being cancelled blind at the job cap.
$InstallDeadlineMinutes = 40
$UpdateDeadlineMinutes = 45

function Start-HangWatchdog([int]$Minutes, [string]$EvidencePath) {
    if (Test-Path -LiteralPath $EvidencePath) { Remove-Item -LiteralPath $EvidencePath -Force }
    $exclude = @()
    if ($script:ChatMock) { $exclude += $script:ChatMock.Id }
    $homes = @($HermesHome, [System.IO.Path]::GetFullPath($HermesHome)) | Select-Object -Unique
    # py-spy is installed next to the driver's Python by the workflow.
    $pyspy = Join-Path (Split-Path $DriverPython) 'py-spy.exe'
    Start-Job -ArgumentList $PID, $Minutes, $EvidencePath, $homes, $exclude, $pyspy -ScriptBlock {
        param($driverPid, $minutes, $out, $homes, $exclude, $pyspy)
        Start-Sleep -Seconds ($minutes * 60)
        $all = @(Get-CimInstance Win32_Process)
        $row = { param($p) '{0,7} <- {1,7}  {2:yyyy-MM-ddTHH:mm:ss}  {3}' -f $p.ProcessId, $p.ParentProcessId, $p.CreationDate, $(if ($p.CommandLine) { $p.CommandLine } else { $p.Name }) }
        $tree = @()
        $frontier = @($driverPid)
        while ($frontier.Count -gt 0) {
            $children = @($all | Where-Object { ($frontier -contains $_.ParentProcessId) -and $_.ProcessId -ne $PID -and -not ($exclude -contains $_.ProcessId) })
            $tree += $children
            $frontier = @($children | ForEach-Object { $_.ProcessId })
        }
        $leg = @($all | Where-Object {
            $cmd = $_.CommandLine
            $_.ProcessId -ne $PID -and $cmd -and @($homes | Where-Object { $cmd.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0
        })
        $lines = @("still running after $minutes minutes", '', "== descendants of the driver (pid $driverPid) ==")
        $lines += @($tree | ForEach-Object { & $row $_ })
        $lines += @('', "== processes naming this leg's HERMES_HOME ==")
        $lines += @($leg | ForEach-Object { & $row $_ })
        $lines += @('', '== every process, oldest first ==')
        $lines += @($all | Sort-Object CreationDate | ForEach-Object { & $row $_ })
        if (Test-Path -LiteralPath $pyspy) {
            foreach ($p in (@($tree) + @($leg) | Where-Object { $_.Name -match '^(python|pythonw|hermes)' } | Sort-Object ProcessId -Unique)) {
                $lines += @('', "== py-spy dump --pid $($p.ProcessId) ($($p.Name)) ==")
                $lines += @(& $pyspy dump --pid $p.ProcessId --nonblocking 2>&1 | ForEach-Object { "$_" })
            }
        } else {
            $lines += @('', "(no Python stacks: $pyspy is missing)")
        }
        Set-Content -LiteralPath $out -Value $lines -Encoding UTF8
        foreach ($victim in (@($tree) + @($leg))) {
            Stop-Process -Id $victim.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-HangWatchdog($Job) {
    if ($Job) {
        Stop-Job -Job $Job -ErrorAction SilentlyContinue
        Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-ManualCardUpdate([string]$ReceiptPath, [string]$TargetSha) {
    Assert-True (Test-Path -LiteralPath $ReceiptPath) "manual update card produced a receipt"
    $manual = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
    Assert-True ($manual.command -match '^hermes update(?:\s|$)') "manual update card instructed hermes update"
    Invoke-HermesUpdate
    Assert-True ((Get-InstalledHead) -eq $TargetSha) "manual update landed on target commit"
    Test-HermesRuns "post-manual-update"
    Assert-True ($null -ne (Get-DesktopExe)) "Hermes.exe still present after manual update"
}

function Clear-HistoricalInstallerChurn {
    # The GUI driver refuses a dirty source tree. v2026.7.1's installer leaves
    # its own state there: `npm install` rewrites package-lock.json on Windows
    # (later installers use `npm ci`, #112378) and v2026.6.19-era installers
    # write an unignored .install_method. Installers through v2026.9.24 also
    # clone under Git for Windows' system core.autocrlf=true and pin false only
    # afterwards, leaving CRLF copies of every text file .gitattributes does not
    # pin to LF (*.mdx, LICENSE, ...). The stat cache hides them except the few
    # written in the index's racy timestamp window, which read as modified with
    # identical index/HEAD blobs. Undo only that installer-generated state in
    # this disposable clone; any other change still fails, listed.
    # porcelain=v2: Invoke-Git trims output, which would eat v1's leading " M".
    $lines = @((Invoke-Git @("-C", $InstallDir, "-c", "core.quotepath=false", "status", "--porcelain=v2", "--untracked-files=all")) -split "\r?\n" |
        Where-Object { $_ })
    if ($lines.Count -eq 0) { return }
    Write-Host "  source status before GUI update:"
    $lines | ForEach-Object { Write-Host "    $_" }
    # --numstat honours --ignore-cr-at-eol (--name-only does not): a modified
    # path with no record and an unchanged mode differs from its index blob
    # only by CRs.
    $content = @{}
    (Invoke-Git @("-C", $InstallDir, "-c", "core.quotepath=false", "diff", "--numstat", "--ignore-cr-at-eol")) -split "\r?\n" |
        Where-Object { $_ } | ForEach-Object { $content[($_ -split "`t", 3)[2]] = $true }
    $locks = @(); $other = @()
    foreach ($line in $lines) {
        $fields = $line -split " ", 9
        if ($fields[0] -eq "1" -and $fields[1] -eq ".M" -and $fields.Count -eq 9 -and
            ($fields[8] -eq "package-lock.json" -or $fields[8] -like "*/package-lock.json" -or
             ($fields[4] -eq $fields[5] -and -not $content.ContainsKey($fields[8])))) {
            $locks += $fields[8]
        } elseif ($line -eq "? .install_method") {
            Add-Content -LiteralPath (Join-Path $InstallDir ".git\info\exclude") -Value "/.install_method"
        } else {
            $other += $line
        }
    }
    Assert-True ($other.Count -eq 0) "installed source has only installer-generated changes (other: $($other -join '; '))"
    if ($locks.Count) {
        # From a file: a v2026.7.1 clone churns hundreds of paths, and passing
        # them as arguments overflows the Windows command line ("The filename
        # or extension is too long"). NUL-separated, literal: no quoting or
        # glob magic applies to a path.
        $pathspecs = Join-Path $WorkRoot "installer-churn.pathspec"
        [System.IO.File]::WriteAllText($pathspecs, (($locks -join "`0") + "`0"), (New-Object System.Text.UTF8Encoding $false))
        Invoke-Git @("--literal-pathspecs", "-C", $InstallDir, "checkout", "--pathspec-from-file=$pathspecs", "--pathspec-file-nul") | Out-Null
    }
    $left = @((Invoke-Git @("-C", $InstallDir, "status", "--porcelain", "--untracked-files=all")) -split "\r?\n" |
        Where-Object { $_ })
    Assert-True ($left.Count -eq 0) "undid only installer-generated source churn before the GUI update"
}

function Invoke-HermesDesktopAppUpdate([string]$TargetSha) {
    # The hermes-desktop launch surface: `hermes desktop` runs its whole
    # real pipeline; the driver intercepts the product's final spawn
    # (argv/cwd/env captured by e2e-assets/launch-capture/sitecustomize.py)
    # and re-executes it under Playwright, which clicks Update now.
    $hermesExe = Get-SourceHermes $InstallDir
    $spec = Join-Path $WorkRoot "launch-spec.json"
    New-Item -ItemType Directory -Path (Join-Path $WorkRoot "logs") -Force | Out-Null
    $log = Join-Path $WorkRoot "logs\desktop-launch-capture.log"

    $capDir = Join-Path $AssetsDir "launch-capture"
    $prevPy = $env:PYTHONPATH
    $prevCap = $env:HERMES_E2E_CAPTURE_LAUNCH
    $env:PYTHONPATH = if ($prevPy) { "$capDir;$prevPy" } else { $capDir }
    $env:HERMES_E2E_CAPTURE_LAUNCH = $spec
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    Push-Location $InstallDir
    try {
        if ($hermesExe.StartsWith((Join-Path $InstallDir '.hermes'), [StringComparison]::OrdinalIgnoreCase)) {
            # The PM launcher runs its interpreter with -I, so PYTHONPATH never
            # imports sitecustomize. Same as installer-script-e2e.sh: ask the
            # launcher for its own isolated command and inject the hook into it.
            & $DriverPython -I (Join-Path $capDir 'pm-launch.py') $hermesExe $spec 2>&1 | Add-TsPrefix | Out-File -Encoding UTF8 $log
        } else {
            # Pre-PM venv console scripts load sitecustomize from PYTHONPATH.
            & $hermesExe desktop 2>&1 | Add-TsPrefix | Out-File -Encoding UTF8 $log
        }
        $capExit = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prevEap
        $env:PYTHONPATH = $prevPy
        $env:HERMES_E2E_CAPTURE_LAUNCH = $prevCap
    }
    Write-LogGroup "hermes desktop (launch capture) transcript" $log
    Assert-True ($capExit -eq 0) "hermes desktop exited 0 during launch capture"
    Assert-True (Test-Path -LiteralPath "$spec.captured") "a launch was actually captured (exit 0 without a launch must not pass)"
    Clear-HistoricalInstallerChurn

    $node = $DriverNode
    $chatOut = Join-Path $ProofRoot 'update-window'
    Remove-Item -LiteralPath (Join-Path $chatOut 'desktop-chat-old.json') -Force -ErrorAction SilentlyContinue
    $script:ChatFailure = $true
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    Push-Location $WorkRoot
    try {
        # 30 min, not the 10 min default: from v2026.9.24 the app's update
        # runs the historical venv->PM takeover plus a full Desktop rebuild
        # (9m43s measured).
        & $node (Join-Path $AssetsDir "launch-from-spec.mjs") --spec $spec `
            --old-sha (Read-State).old --chat-out $chatOut --mock-url $env:HERMES_E2E_MOCK_URL `
            --result (Join-Path $HermesHome ".hermes-update-result.json") `
            --expect-sha $TargetSha --repo-dir $InstallDir --timeout-ms 1800000 2>&1 |
            ForEach-Object { Write-Host "  pw| $_" }
        $driveExit = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prevEap
    }
    Confirm-OldChat $chatOut
    $manualReceipt = Join-Path $chatOut 'manual-update.json'
    if ($driveExit -eq 42) {
        Invoke-ManualCardUpdate $manualReceipt $TargetSha
        return
    }
    Assert-True ($driveExit -eq 0) "app driven via captured hermes desktop spec; update completed"

    # The production updater relaunches Hermes. Close that verified window
    # normally so the test-owned checkpoint starts and owns its own backend.
    $desktopExe = Get-DesktopExe
    $deadline = (Get-Date).AddMinutes(5)
    $windows = @()
    while ((Get-Date) -lt $deadline) {
        $windows = @(Get-VerifiedDesktopWindows $desktopExe)
        if ($windows.Count -eq 1) { break }
        Start-Sleep -Seconds 2
    }
    Assert-True ($windows.Count -eq 1) "updated desktop relaunched exactly one verified window"
    $script:ChatFailure = $true
    Close-VerifiedDesktop $desktopExe $windows[0].Id
}

# ----------------------------------------------------------------------------
# Phase: stage -- serve.git with `main` at OLD (advanced to HEAD by the update phase)
# ----------------------------------------------------------------------------
# Mirror of resolve_update_ref's NEXT arm in e2e-assets/installer-common.sh:
# a synthetic child of $Parent whose tree adds one marker file (a real diff,
# not an empty fast-forward), written to the object store only -- no ref, no
# worktree change. A local `clone --bare` copies objects/ wholesale, which is
# how it reaches serve.git. A throwaway index stands in for mktree so no
# NUL-delimited stdin has to cross PowerShell's native pipe.
function New-NextCommit([string]$Repo, [string]$Parent) {
    $marker = Join-Path $WorkRoot "next-marker.txt"
    Set-Content -LiteralPath $marker -Encoding ASCII -Value "synthetic next commit for the HEAD -> NEXT install E2E leg"
    $blob = Invoke-Git @("-C", $Repo, "hash-object", "-w", "--no-filters", $marker)
    $saved = @{}
    $vars = @{
        GIT_INDEX_FILE = (Join-Path $WorkRoot "next.index")
        GIT_AUTHOR_NAME = "Hermes E2E"; GIT_AUTHOR_EMAIL = "e2e@hermes.invalid"
        GIT_COMMITTER_NAME = "Hermes E2E"; GIT_COMMITTER_EMAIL = "e2e@hermes.invalid"
    }
    foreach ($k in $vars.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $vars[$k]) }
    try {
        Invoke-Git @("-C", $Repo, "read-tree", $Parent) | Out-Null
        Invoke-Git @("-C", $Repo, "update-index", "--add", "--cacheinfo", "100644,$blob,.hermes-e2e-next") | Out-Null
        $tree = Invoke-Git @("-C", $Repo, "write-tree")
        return Invoke-Git @("-C", $Repo, "commit-tree", $tree, "-p", $Parent, "-m", "e2e: synthetic next commit")
    } finally {
        foreach ($k in $vars.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
        Remove-Item -LiteralPath $vars.GIT_INDEX_FILE -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-PhaseStage {
    Write-Step "STAGE: bare serve repo, main -> OLD (install base)"

    if (Test-Path -LiteralPath $WorkRoot) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $WorkRoot "logs") -Force | Out-Null
    # The purge above deleted the redirect gitconfig; re-arm it so the
    # bare-clone below (and everything after) sees the redirect file.
    Set-GitRedirect

    # OLD: explicit -InstallRef, or the newest release tag -- the version a
    # user who installed on release day is on.
    $oldRef = $InstallRef
    if (-not $oldRef -or $oldRef -eq "auto") {
        # Parens matter: without them PowerShell binds -split as an
        # argument to Invoke-Git instead of an operator on its result.
        $tagList = Invoke-Git @("-C", $RepoRoot, "tag", "--list", "v*", "--sort=-creatordate")
        $oldRef = ($tagList -split "\r?\n" | Select-Object -First 1)
        if (-not $oldRef) { throw "no v* release tags in the checkout and no -InstallRef given -- cannot pick an OLD version" }
    }
    $old = Invoke-Git @("-C", $RepoRoot, "rev-parse", "$oldRef^{commit}")
    Write-Host "  OLD  ($oldRef): $old"
    # NEXT is minted before the clone so it rides along into serve.git.
    $targetLabel = $UpdateRef
    $current = if ($UpdateRef -eq "NEXT") { New-NextCommit $RepoRoot $old } else {
        Invoke-Git @("-C", $RepoRoot, "rev-parse", "${UpdateRef}^{commit}")
    }
    Write-Host "  update target ($targetLabel): $current"
    Assert-True ($old -ne $current) "OLD differs from $targetLabel (an update is genuinely available)"

    # Bare-clone the checkout: this is the repo the installer and updater
    # actually talk to. Local-path clone hardlinks objects, so it's fast
    # even for full history. The published installer carries NO commit pin
    # (Pin { commit: None, branch: main }) -- it installs whatever `main`
    # serves, so staging OLD means parking `main` there; the update phase
    # advances it to HEAD.
    Invoke-Git @("clone", "--bare", "--quiet", $RepoRoot, $ServeRepo) | Out-Null
    Invoke-Git @("-C", $ServeRepo, "cat-file", "-e", "$current^{commit}") | Out-Null
    Invoke-Git @("-C", $ServeRepo, "update-ref", "refs/heads/main", $old) | Out-Null
    Invoke-Git @("-C", $ServeRepo, "symbolic-ref", "HEAD", "refs/heads/main") | Out-Null

    # Belt-and-braces: SOME installer builds do bake a -Commit pin. A pinned
    # sha is in serve.git's history but not at a ref tip, so the redirected
    # fetch needs any-SHA1 upload-pack permission (GitHub grants the
    # equivalent for fetch of reachable commits).
    Invoke-Git @("-C", $ServeRepo, "config", "uploadpack.allowAnySHA1InWant", "true") | Out-Null
    Write-Host "  serve.git: uploadpack.allowAnySHA1InWant=true (installer commit pin, if any)"

    @{ old = $old; old_ref = $oldRef; current = $current; target_label = $targetLabel } |
        ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
    Write-Host "  state written: $StatePath"
    New-Item -ItemType Directory -Path $ProofRoot -Force | Out-Null
}

# --- plugin upgrade-preservation hooks -------------------------------------
# A tagged upgrade must not delete or modify anything under the active
# home's plugins/** or any profile's plugins/** tree: wrapper markers
# (mnemosyne-wrapper.json), symlinked runtimes, and the externally-owned
# sidecar witness outside the home. Fixtures are directory-only (no
# pyproject in the scanned root, nothing downloaded). Snapshot is taken
# after install, verified after update.
function Seed-PreservationFixtures {
    $external = Join-Path $WorkRoot "external-mnemosyne-runtime"
    & $DriverPython (Join-Path $AssetsDir "verify-plugin-preservation.py") seed --home $HermesHome --external $external
    if ($LASTEXITCODE -ne 0) { throw "could not seed fresh preservation fixtures (exit $LASTEXITCODE)" }
}

function Invoke-PreserveSnapshot {
    $out = Join-Path $WorkRoot "plugin-preservation-snapshot.json"
    if (Test-Path -LiteralPath $out) { throw "refusing to overwrite an existing preservation snapshot" }
    Seed-PreservationFixtures
    & $DriverPython (Join-Path $AssetsDir "verify-plugin-preservation.py") snapshot --home $HermesHome --out $out
    if ($LASTEXITCODE -ne 0) { throw "plugin preservation snapshot failed (exit $LASTEXITCODE)" }

    Write-Host "  pre-upgrade plugin snapshot: $out"
}

function Invoke-PreserveVerify {
    $snap = Join-Path $WorkRoot "plugin-preservation-snapshot.json"
    if (-not (Test-Path -LiteralPath $snap)) { throw "no pre-upgrade plugin snapshot at $snap; cannot verify preservation" }
    & $DriverPython (Join-Path $AssetsDir "verify-plugin-preservation.py") verify --home $HermesHome --snapshot $snap `
        --report (Join-Path $WorkRoot "logs\plugin-preservation-report.json")
    if ($LASTEXITCODE -ne 0) { throw "plugin preservation violated by the upgrade (exit $LASTEXITCODE); see the report for deleted/modified entries" }
    Write-Host "  plugins/** and profile plugin trees survived the upgrade intact"
}

# ----------------------------------------------------------------------------
# User-state preservation: the user's OWN durable state, produced through the
# ordinary CLI (never seeded by us), snapshotted before the upgrade and
# verified after it. Complements the plugin-tree contract above, which owns
# plugins/** only.
# ----------------------------------------------------------------------------

function Get-UserStateSessionCount {
    # A real chat turn must actually create a session; if it silently does not,
    # the preservation check below would be testing nothing.
    $probe = Join-Path $WorkRoot 'user-state-session-count.py'
    if (-not (Test-Path -LiteralPath $probe)) {
        @'
import sqlite3, sys
try:
    con = sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True)
    print(con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
except Exception:
    print(-1)
'@ | Set-Content -LiteralPath $probe -Encoding ASCII
    }
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $value = (& $DriverPython $probe (Join-Path $HermesHome 'state.db') 2>$null | Out-String).Trim() }
    finally { $ErrorActionPreference = $prevEap }
    if ($value -match '^-?\d+$') { return [int]$value }
    return -1
}

function Invoke-UserStateActions {
    # Everything here is a command a user would run against the real installed
    # CLI with a real (mocked-inference) provider configured.
    $hermes = Get-SourceHermes $InstallDir
    if (-not $script:ChatMock) {
        # Same mock + config writer the desktop chat checkpoints use, so the
        # leg has a genuinely configured provider rather than a dummy key.
        $script:ChatMock = Start-DesktopJourneyMock $DriverNode $AssetsDir $WorkRoot $HermesHome $ProofRoot
    }
    $prevLazy = $env:HERMES_DISABLE_LAZY_INSTALLS
    $prevEap = $ErrorActionPreference
    try {
        $env:HERMES_DISABLE_LAZY_INSTALLS = '1'
        $ErrorActionPreference = 'Continue'

        # Probe, do not assume (the harness rule for old refs).
        $chatHelp = (& $hermes chat --help 2>&1 | Out-String)
        if (-not ($chatHelp -match '(^|\s)-q(\s|,|$)' -or $chatHelp -match '--quiet')) {
            throw 'the installed CLI has no one-shot chat flag; this leg cannot produce a session through the user path'
        }
        # Since a5c7eed (v2026.9.21+) `-q` on a real TTY seeds an INTERACTIVE session and
        # only answers-and-exits with --oneshot (or on non-TTY stdio). The pseudoconsole
        # below IS a TTY, so without --oneshot the turn answers and then sits at the
        # prompt forever. Older tags have no --oneshot and exit after -q on their own.
        $oneshot = @()
        if ($chatHelp -match '--oneshot') { $oneshot = @('--oneshot') }
        $before = Get-UserStateSessionCount
        $log = Join-Path $WorkRoot 'logs\user-state-chat.log'
        # A released tag prints through prompt_toolkit, whose Windows output object needs
        # a console screen buffer: piping the CLI's stdout into the log takes that away
        # and the turn dies with NoConsoleScreenBufferError. Run it under a real
        # pseudoconsole (pty-run.py) and keep the capture.
        & $DriverPython -B (Join-Path $AssetsDir 'pty-run.py') --out $log --timeout 300 -- $hermes chat -q "Reply with the single word: ok" @oneshot
        $chatExit = $LASTEXITCODE
        Write-LogGroup 'first real chat turn' $log
        if ($chatExit -eq 124) {
            throw "the first chat turn never exited (still running after 300s; flags: chat -q $($oneshot -join ' ')); see $log"
        }
        if ($chatExit -ne 0) { throw "the first chat turn failed (exit $chatExit); see $log" }
        $after = Get-UserStateSessionCount
        # A fresh install has no state.db until the first turn: -1 means "no
        # readable db yet", the expected starting point, not a failure.
        if ($before -lt 0) { $before = 0 }
        if ($after -lt 0) { $after = 0 }
        if (-not ($after -gt $before)) {
            throw "the chat turn produced no session row (state.db sessions $before -> $after)"
        }
        Write-Host "  a real turn created a session (state.db sessions $before -> $after)"

        if (-not (Test-Path -LiteralPath (Join-Path $HermesHome 'auth.json'))) {
            # A starting tag may not have this subcommand yet: a harness
            # limitation, not a preservation failure.
            & $hermes auth add --help *> $null
            if ($LASTEXITCODE -ne 0) {
                Write-Host '  SKIP hermes auth add does not exist on this ref; auth.json is not covered by this leg'
            }
            else {
            # The provider id and the flags are vintage surfaces, so probe them
            # like the rest of this harness does. v2026.8.31 answers "Unknown
            # provider: openai" -- _is_known_provider accepts a registry provider,
            # 'openrouter', or a custom pool -- and HEAD prompts for an optional
            # label unless --label is given, which EOFs with no tty. Take the
            # first provider the installed CLI accepts.
            $authLog = Join-Path $WorkRoot 'logs\user-state-auth.log'
            $labelFlags = @()
            if ((& $hermes auth add --help 2>&1 | Out-String) -match '--label') {
                $labelFlags = @('--label', 'e2e-preservation')
            }
            $added = $false
            foreach ($provider in @('openrouter', 'anthropic')) {
                Add-Content -LiteralPath $authLog -Value "=== hermes auth add $provider ==="
                & $hermes auth add $provider --type api-key `
                    --api-key 'e2e-preservation-not-a-real-key' @labelFlags 2>&1 |
                    Out-File -Encoding UTF8 -Append $authLog
                if (Test-Path -LiteralPath (Join-Path $HermesHome 'auth.json')) {
                    $added = $true
                    break
                }
            }
            if (-not $added) {
                throw "hermes auth add failed for openrouter and anthropic; see $authLog"
            }
            Write-Host '  a pooled credential exists (auth.json)'
            }
        }

        if (-not (Test-Path -LiteralPath (Join-Path $HermesHome 'profiles\e2e-second'))) {
            # Same vintage surface as auth add above: a starting tag may predate
            # the profile command entirely, and that is a harness limitation,
            # not a preservation failure.
            & $hermes profile create --help *> $null
            if ($LASTEXITCODE -ne 0) {
                Write-Host '  SKIP hermes profile create does not exist on this ref; profiles/e2e-second is not covered by this leg'
            }
            else {
            & $hermes profile create e2e-second 2>&1 |
                Out-File -Encoding UTF8 (Join-Path $WorkRoot 'logs\user-state-profile.log')
            if ($LASTEXITCODE -ne 0) { throw 'hermes profile create failed' }
            if (-not (Test-Path -LiteralPath (Join-Path $HermesHome 'profiles\e2e-second'))) {
                throw 'hermes profile create produced no profile dir'
            }
            # Factory templates migrate intentionally; preserve an authored profile instead.
            Add-Content -LiteralPath (Join-Path $HermesHome 'profiles\e2e-second\SOUL.md') `
                -Encoding UTF8 -Value "`nUser preference: preserve my e2e-second profile identity across upgrades."
            Write-Host '  a second profile exists (profiles/e2e-second)'
            }
        }
    }
    finally {
        $env:HERMES_DISABLE_LAZY_INSTALLS = $prevLazy
        $ErrorActionPreference = $prevEap
    }
}

function Invoke-UserStateSnapshot {
    $snap = Join-Path $WorkRoot 'user-state-snapshot.json'
    if (Test-Path -LiteralPath $snap) { throw 'refusing to overwrite an existing user-state snapshot' }
    & $DriverPython (Join-Path $AssetsDir 'verify-user-state.py') snapshot --home $HermesHome --out $snap
    if ($LASTEXITCODE -ne 0) { throw "user-state snapshot failed (exit $LASTEXITCODE)" }
    Write-Host "  pre-upgrade user-state snapshot: $snap"
}

function Invoke-UserStateVerify {
    $snap = Join-Path $WorkRoot 'user-state-snapshot.json'
    if (-not (Test-Path -LiteralPath $snap)) {
        throw 'no pre-upgrade user-state snapshot; cannot claim preservation'
    }
    $report = Join-Path $WorkRoot 'logs\user-state-report.json'
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        & $DriverPython (Join-Path $AssetsDir 'verify-user-state.py') verify --home $HermesHome `
            --snapshot $snap --report $report
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prevEap }
    if ($code -ne 0) {
        throw "the upgrade changed the user's own state (exit $code); report at $report"
    }
    Write-Host "  the user's own durable state survived the upgrade"
}

function Assert-RedirectIsTransportOnly {
    # The redirect must stay at TRANSPORT level: `hermes update` resolves its
    # channel from the release archive and validates the record against
    # `git config --get remote.origin.url`. If the configured URL ever looked
    # like the rehearsal source, channel resolution would fail and this leg
    # would be testing a fork install rather than the real user path.
    $official = @('https://github.com/NousResearch/hermes-agent.git',
                  'git@github.com:NousResearch/hermes-agent.git')
    $configured = (Invoke-Git @('-C', $InstallDir, 'config', '--get', 'remote.origin.url') | Out-String).Trim()
    Assert-True ($official -contains $configured) "origin stays configured as an official URL (got '$configured')"
    $real = if ($env:HERMES_E2E_REAL_GIT) { $env:HERMES_E2E_REAL_GIT } else { 'git' }
    $observed = (& $real -C $InstallDir remote get-url origin 2>$null | Out-String).Trim()
    Assert-True ($observed -match 'serve\.git|^file://') "git transport is redirected to the staged repo (got '$observed')"
}

function Assert-UserShims {
    # A launcher left pointing at a vanished tree is the "update lost
    # something" shape a checkout-hash assertion cannot see.
    $hermes = Get-SourceHermes $InstallDir
    Assert-True (Test-Path -LiteralPath $hermes) "a usable launcher still exists after the upgrade ($hermes)"
    $userShim = Join-Path $HermesHome 'bin\hermes.exe'
    if (-not (Test-Path -LiteralPath $userShim)) { $userShim = Join-Path $HermesHome 'bin\hermes.cmd' }
    if (Test-Path -LiteralPath $userShim) {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try {
            & $userShim --version 2>&1 | Out-Null
            $shimExit = $LASTEXITCODE
        }
        finally { $ErrorActionPreference = $prevEap }
        Assert-True ($shimExit -eq 0) "the $HermesHome\bin launcher still runs after the upgrade"
    }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath) {
        # The fixture home contains ``..`` while Windows can persist the same
        # directory canonically. Compare path identities, not raw substrings.
        $expectedUserBin = [IO.Path]::GetFullPath((Join-Path $HermesHome 'bin')).TrimEnd('\')
        $userPathEntries = @(
            foreach ($entry in ($userPath -split ';')) {
                if (-not $entry) { continue }
                $expanded = [Environment]::ExpandEnvironmentVariables($entry)
                try { [IO.Path]::GetFullPath($expanded).TrimEnd('\') }
                catch { $expanded.TrimEnd('\') }
            }
        )
        Assert-True ($userPathEntries -icontains $expectedUserBin) `
            "the USER PATH still exposes $expectedUserBin (actual: $userPath)"
    }
}

function Invoke-PhaseInstall {
    # The source install lands on OLD, hermes runs, and state carries how OLD
    # landed so any update route can follow it. A source install builds no
    # desktop app.
    $state = Read-State
    $script:ExpectedDesktop = 'absent'
    # Isolated install target; serve.git's file:// origin
    # looks like a fork to the updater, whose "add the official repo as
    # upstream?" prompt would hang a headless run - the marker is the
    # product's own suppression mechanism.
    $env:HERMES_HOME = $HermesHome
    New-Item -ItemType Directory -Path $HermesHome -Force | Out-Null
    Write-Step "INSTALL (script): OLD's own install.ps1, headless"
    Invoke-RefInstaller $state.old "old"
    Assert-True ((Get-InstalledHead) -eq $state.old) "installed checkout is at OLD"
    Test-HermesRuns "post-install-script"
    Invoke-DesktopCheckpoint 'old' $state.old $InstallMethod
    Assert-RedirectIsTransportOnly
    Invoke-UserStateActions
}

function Invoke-PhaseUpdate {
    $state = Read-State
    # Only the source desktop launch route leaves a built desktop app behind;
    # every other source route keeps the source-only install.
    $script:ExpectedDesktop = if ($Route -eq 'hermes-desktop-app-update') { 'present' } else { 'absent' }
    $env:HERMES_HOME = $HermesHome
    # Match the POSIX driver's explicit opt-out when a detached updater bypasses
    # the PATH shim and sees our local transport as a fork.
    New-Item -ItemType File -Path (Join-Path $HermesHome ".skip_upstream_prompt") -Force | Out-Null

    # The update becomes available the way it does for a real user: the
    # remote's main moves forward.
    # The mock provider is journey setup, not an upgrade mutation. Configure it
    # before preservation snapshots so its stable endpoint is part of baseline state.
    if ($Route -eq 'hermes-desktop-app-update') {
        Start-JourneyChat
    }
    Set-SourceMainChannel $InstallDir
    # Snapshot every plugin tree BEFORE the upgrade moves anything.
    Invoke-PreserveSnapshot
    # ... and the user's own durable state, produced by the install phase
    # through the ordinary CLI.
    Invoke-UserStateSnapshot
    Invoke-Git @("-C", $ServeRepo, "update-ref", "refs/heads/main", $state.current) | Out-Null
    Write-Host "  serve.git main advanced to $($state.current)"

    switch ($Route) {
        "hermes-desktop-app-update" {
            Invoke-HermesDesktopAppUpdate $state.current
        }
        "hermes-update" {
            Invoke-HermesUpdate
        }
        "installer-script" {
            # A user re-running the one-liner today gets the CURRENT script.
            Invoke-RefInstaller $state.current "head"
        }
    }

    Assert-True ((Get-InstalledHead) -eq $state.current) "checkout landed on $($state.target_label)"
    Test-HermesRuns "post-update"
    Assert-UserShims
    Invoke-PreserveVerify
    Invoke-UserStateVerify
    Invoke-DesktopCheckpoint 'new' $state.current $Route
}

function Invoke-CheckedPhaseUpdate {
    Remove-Item -LiteralPath (Join-Path $WorkRoot "known-failure.json") -Force -ErrorAction SilentlyContinue
    # Only evidence produced by this update attempt can match an exception.
    foreach ($oldLog in @((Join-Path $WorkRoot "logs\update.log"), (Join-Path $HermesHome "logs\desktop.log"))) {
        if (Test-Path -LiteralPath $oldLog) { Move-Item -LiteralPath $oldLog -Destination "$oldLog.before-update" -Force }
    }
    try {
        Invoke-PhaseUpdate
    } catch {
        $failure = $_
        if ($script:ChatFailure) { throw $failure }
        $node = $DriverNode
        $classification = & $node (Join-Path $AssetsDir "known-failures.cjs") $WorkRoot $InstallMethod $Route $failure.Exception.Message
        $classificationExit = $LASTEXITCODE
        if ($classificationExit -ne 0) { throw $failure }
        $receipt = ($classification | Out-String) | ConvertFrom-Json
        Write-Host "KNOWN FAILURE [$($receipt.id)]: $($receipt.title)"
        Write-Host "  $($receipt.explanation)"
        if ($env:GITHUB_OUTPUT) {
            Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "known_failure=$($receipt.id)" -Encoding UTF8
        }
        if ($env:GITHUB_STEP_SUMMARY) {
            Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Encoding UTF8 -Value "Known historical failure: $($receipt.title). See the result chart footnote and uploaded known-failure.json."
        }
    }
}

function Invoke-PhaseVerifyStamp {
    # Runs AFTER everything (install, update, the new runtime's launch and its
    # smoke checks): the bootstrap-complete receipt and the checkout's source
    # stamp must both tell the truth about the final HEAD. A separate phase —
    # not an install-phase check — because the bootstrap marker can complete
    # on a LATER run than the install itself.
    $state = Read-State
    $head = Get-InstalledHead
    Assert-True ($head -match '^[0-9a-f]{40}$') "installed HEAD readable: '$head'"
    Write-Host "  install HEAD: $($head.Substring(0, 12))"
    $stampPath = Join-Path $InstallDir '.hermes-bootstrap-complete'
    # FAIL lines go to stderr; under "Stop", PowerShell 5.1 would throw on the first one.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $verdict = @(& $DriverPython -B (Join-Path $RepoRoot 'scripts\verify-bootstrap-version-stamp.py') `
            --stamp $stampPath --repo $InstallDir --expect-commit $state.current 2>&1 | ForEach-Object { "$_" })
        $verifyExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prevEap }
    $verdict | ForEach-Object { Write-Host $_ }
    if ($verifyExit -eq 0) { return }
    throw "stamp verification failed (exit $verifyExit)"
}

# ----------------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------------
Write-Host "Windows install/update E2E driver (real user flows)"
Write-Host "  phase:    $Phase"
Write-Host "  install:  $InstallMethod"
Write-Host "  route:    $Route"
Write-Host "  repo:     $RepoRoot"
Write-Host "  workroot: $WorkRoot"

$script:RealGitExe = (Get-Command git.exe -ErrorAction Stop).Source
# The HEAD start is the fresh-machine leg: HEAD's installer on a box with
# nothing on it, git included (see Set-GitRedirect).
$script:FreshMachine = ($InstallRef -eq "HEAD")

Set-GitRedirect

try {
switch ($Phase) {
    "stage"   { Invoke-PhaseStage }
    "install" { Invoke-SourceBuild { Invoke-PhaseInstall } }
    "update"  { Invoke-SourceBuild { Invoke-CheckedPhaseUpdate } }
    "verify-stamp" { Invoke-PhaseVerifyStamp }
    "all" {
        Invoke-PhaseStage
        Invoke-SourceBuild { Invoke-PhaseInstall }
        Invoke-SourceBuild { Invoke-CheckedPhaseUpdate }
        Invoke-PhaseVerifyStamp
    }
}

} finally {
    if ($script:ChatMock -and -not $script:ChatMock.HasExited) {
        Stop-Process -Id $script:ChatMock.Id -ErrorAction SilentlyContinue
    }
}
Write-Host ""
Write-Host "Phase '$Phase' completed successfully."
