<#
.SYNOPSIS
    Builds a ready-to-use, fully portable Windows x64 bundle of FileRouter.

.DESCRIPTION
    Produces a self-contained .zip that needs NO Python installation on the
    target machine. The bundle embeds:
      * the official Python "embeddable" runtime (python.org),
      * the FileRouter package and all runtime dependencies
        (PyYAML, jsonschema, python-gnupg, PGPy, pywin32),
      * a commented example configuration,
      * .bat launchers for the CLI, the doctor and the Windows service,
      * a French quick-start README.

    The user just unzips and runs `filerouter.bat`. GnuPG (Gpg4win) is only
    required if the `gnupg` encryption backend is enabled; the pure-Python
    `pgpy` backend works with no external tool.

.PARAMETER PythonVersion
    Python 3.12.x patch release to embed (must exist on python.org/ftp).

.PARAMETER AppVersion
    Version label used in the bundle/zip name.

.PARAMETER OutputDir
    Where the staging tree and final .zip are written (default: <repo>\dist).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-portable-win.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.12.8",
    [string]$AppVersion    = "1.0.0",
    [string]$OutputDir     = "",
    # GnuPG install root (containing bin\gpg.exe) to embed for the `gnupg`
    # backend. Empty = auto-detect on the build machine (PATH, Program Files).
    [string]$GnuPGDir      = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference     = "SilentlyContinue"   # faster Invoke-WebRequest downloads

# -- paths -------------------------------------------------------------------
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputDir) { $OutputDir = Join-Path $RepoRoot "dist" }

# Version-LESS internal folder so a new release can be extracted into the SAME
# directory to upgrade in place; the ZIP file name still carries the version.
$FolderName = "filerouter"
$ZipName    = "filerouter-$AppVersion-win64"
$CacheDir   = Join-Path $OutputDir ".cache"
$StageRoot  = Join-Path $OutputDir "stage"
$BundleDir  = Join-Path $StageRoot $FolderName
$PythonDir  = Join-Path $BundleDir "python"
$ZipPath    = Join-Path $OutputDir "$ZipName.zip"

$EmbedUrl  = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$EmbedZip  = Join-Path $CacheDir "python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$GetPip    = Join-Path $CacheDir "get-pip.py"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

Write-Step "FileRouter portable bundle builder"
Write-Host "    repo        : $RepoRoot"
Write-Host "    python      : $PythonVersion (embeddable amd64)"
Write-Host "    app version : $AppVersion"
Write-Host "    output      : $OutputDir"

# -- 0. clean staging, prepare dirs -----------------------------------------
Write-Step "Preparing directories"
if (Test-Path $StageRoot) { Remove-Item $StageRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $CacheDir, $BundleDir, $PythonDir | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

# -- 1. download (cached) embeddable Python + get-pip ------------------------
Write-Step "Fetching Python embeddable + get-pip (cached in $CacheDir)"
if (-not (Test-Path $EmbedZip)) {
    Write-Host "    downloading $EmbedUrl"
    Invoke-WebRequest -Uri $EmbedUrl -OutFile $EmbedZip
} else { Write-Host "    using cached $($EmbedZip | Split-Path -Leaf)" }
if (-not (Test-Path $GetPip)) {
    Write-Host "    downloading $GetPipUrl"
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPip
} else { Write-Host "    using cached get-pip.py" }

# -- 2. extract the embeddable runtime --------------------------------------
Write-Step "Extracting embeddable runtime"
Expand-Archive -Path $EmbedZip -DestinationPath $PythonDir -Force
$PythonExe = Join-Path $PythonDir "python.exe"
if (-not (Test-Path $PythonExe)) { throw "python.exe not found after extraction" }

# -- 3. enable site-packages in the ._pth file ------------------------------
# The embeddable runtime ships a `pythonNNN._pth` that disables `site`. We
# uncomment `import site` and add Lib\site-packages so pip-installed packages
# (and our app) are importable.
Write-Step "Enabling site-packages (._pth patch)"
$PthFile = Get-ChildItem -Path $PythonDir -Filter "python*._pth" | Select-Object -First 1
if (-not $PthFile) { throw "no python*._pth file in the embeddable runtime" }
$pth = Get-Content $PthFile.FullName
$pth = $pth -replace '^\s*#\s*import site\s*$', 'import site'
if ($pth -notmatch 'import site') { $pth += 'import site' }
if ($pth -notmatch 'Lib\\site-packages') { $pth += 'Lib\site-packages' }
Set-Content -Path $PthFile.FullName -Value $pth -Encoding ascii
Write-Host "    patched $($PthFile.Name)"

# -- 4. bootstrap pip inside the embeddable runtime -------------------------
Write-Step "Bootstrapping pip"
& $PythonExe $GetPip --no-warn-script-location --no-cache-dir
if ($LASTEXITCODE -ne 0) { throw "get-pip.py failed (exit $LASTEXITCODE)" }

# -- 5. install FileRouter + all runtime deps into the runtime --------------
# Installs from the repo with the windows/gnupg/pgpy extras so the bundle can
# run as a Windows service and use either OpenPGP backend out of the box.
#
# The embeddable runtime cannot bootstrap pip's *build isolation* env (the
# ._pth lockdown hides setuptools from the isolated sub-process). So we install
# the build backend (setuptools+wheel, prebuilt wheels) into the runtime first,
# then build FileRouter with --no-build-isolation against it. Runtime deps
# (PyYAML, jsonschema, python-gnupg, PGPy, pywin32) are still resolved normally.
Write-Step "Installing build backend (setuptools + wheel)"
& $PythonExe -m pip install --no-warn-script-location --no-cache-dir "setuptools>=68" wheel
if ($LASTEXITCODE -ne 0) { throw "installing build backend failed (exit $LASTEXITCODE)" }

Write-Step "Installing FileRouter + dependencies into the runtime"
Push-Location $RepoRoot
try {
    & $PythonExe -m pip install --no-warn-script-location --no-cache-dir `
        --no-build-isolation ".[windows,gnupg,pgpy]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }
} finally { Pop-Location }

# -- 6. wire pywin32 for imports AND for the Windows service ----------------
# (a) pywin32 drops pywintypes/pythoncom DLLs in site-packages\pywin32_system32;
#     copy them next to python.exe so `import win32*` works without the (admin)
#     pywin32_postinstall step.
# (b) pythonservice.exe (the SCM host process) must sit next to python312.dll
#     and the ._pth so the embedded interpreter initializes with the right
#     prefix. pywin32 locates it via dirname(sys.executable) first, so placing
#     a copy in the runtime root makes the installed service use this one.
Write-Step "Wiring pywin32 native DLLs + pythonservice.exe"
$Pw32 = Join-Path $PythonDir "Lib\site-packages\pywin32_system32"
if (Test-Path $Pw32) {
    Copy-Item (Join-Path $Pw32 "*.dll") -Destination $PythonDir -Force
    Write-Host "    copied $((Get-ChildItem $Pw32 -Filter *.dll).Count) pywin32 DLL(s) to runtime root"
} else {
    Write-Warning "pywin32_system32 not found; Windows service support may be limited"
}
$SvcExe = Join-Path $PythonDir "Lib\site-packages\win32\pythonservice.exe"
if (Test-Path $SvcExe) {
    Copy-Item $SvcExe -Destination $PythonDir -Force
    Write-Host "    copied pythonservice.exe to runtime root"
} else {
    Write-Warning "pythonservice.exe not found; the native Windows service may not start"
}

# -- 7. drop the example config (TEMPLATE only) -----------------------------
# We ship config.example.yaml, never config.yaml: the user copies it once to
# config\config.yaml (or elsewhere). Because the archive never contains
# config.yaml, re-extracting a new bundle over an existing install upgrades the
# program WITHOUT ever overwriting the operator's real configuration.
Write-Step "Adding example configuration (template)"
$ConfigDir = Join-Path $BundleDir "config"
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
Copy-Item (Join-Path $RepoRoot "docs\examples\config.example.yaml") `
          (Join-Path $ConfigDir "config.example.yaml") -Force

# -- 7b. embed the GnuPG binaries (100% self-contained gnupg backend) -------
# python-gnupg only wraps gpg(.exe); the binary itself must travel in the
# bundle so the `gnupg` backend works with nothing installed on the target.
# We copy a GnuPG install's bin/ (gpg.exe, gpg-agent, dirmngr, gpgconf, libs).
Write-Step "Embedding GnuPG binaries"
function Find-GnuPGDir {
    if ($GnuPGDir) { return $GnuPGDir }
    $gpg = Get-Command gpg -ErrorAction SilentlyContinue
    if ($gpg) { return (Split-Path (Split-Path $gpg.Source -Parent) -Parent) }
    foreach ($p in @("$env:ProgramFiles\GnuPG", "${env:ProgramFiles(x86)}\GnuPG",
                     "$env:ProgramFiles\Gpg4win", "${env:ProgramFiles(x86)}\Gpg4win")) {
        if (Test-Path (Join-Path $p "bin\gpg.exe")) { return $p }
    }
    return $null
}
$gnupgRoot = Find-GnuPGDir
if (-not $gnupgRoot -or -not (Test-Path (Join-Path $gnupgRoot "bin\gpg.exe"))) {
    throw "GnuPG not found on the build machine. Install GnuPG/Gpg4win or pass " +
          "-GnuPGDir <path-with-bin\gpg.exe>. (Required to embed the gnupg backend.)"
}
$gnupgDst = Join-Path $BundleDir "gnupg\bin"
New-Item -ItemType Directory -Force -Path $gnupgDst | Out-Null
Copy-Item (Join-Path $gnupgRoot "bin\*") -Destination $gnupgDst -Recurse -Force
Write-Host "    embedded GnuPG from $gnupgRoot ($((& (Join-Path $gnupgDst 'gpg.exe') --version | Select-Object -First 1))"

# -- 7c. ship 100% of the documentation + the main README -------------------
Write-Step "Adding full documentation + README.md"
Copy-Item (Join-Path $RepoRoot "README.md") (Join-Path $BundleDir "README.md") -Force
Copy-Item (Join-Path $RepoRoot "LICENSE")   (Join-Path $BundleDir "LICENSE")   -Force
Copy-Item (Join-Path $RepoRoot "docs") (Join-Path $BundleDir "docs") -Recurse -Force
Write-Host "    copied README.md, LICENSE and docs\ ($((Get-ChildItem (Join-Path $BundleDir 'docs') -Recurse -File).Count) files)"

# -- 7d. dependency manifest (vulnerability tracking / reproducibility) ------
# Records the EXACT version of every embedded component so operators can match
# them against CVE/GHSA advisories and rebuild an identical bundle.
Write-Step "Writing VERSIONS.txt (dependency manifest)"
$freeze  = (& $PythonExe -m pip freeze) -join "`r`n"
$pyVer   = ((& $PythonExe --version) 2>&1 | Out-String).Trim()
$gpgVer  = (& (Join-Path $gnupgDst "gpg.exe") --version | Select-Object -First 1)
$builtAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$versionsTxt = @"
FileRouter portable bundle - dependency manifest
=================================================
Bundle      : filerouter $AppVersion (Windows x64, portable)
Built (UTC) : $builtAt
Python      : $pyVer
GnuPG       : $gpgVer

This file lists the EXACT version of every embedded Python package so you can
cross-check them against vulnerability advisories (CVE / GHSA) and reproduce an
identical bundle. Regenerate at any time with:  python\python.exe -m pip freeze

Python packages (pip freeze)
----------------------------
$freeze
"@
Set-Content -Path (Join-Path $BundleDir "VERSIONS.txt") -Value $versionsTxt -Encoding utf8
Write-Host "    wrote VERSIONS.txt ($(($freeze -split "`r`n").Count) packages)"

# -- 8. write launchers ------------------------------------------------------
Write-Step "Writing .bat launchers"
# Each launcher points python-gnupg at the embedded gpg.exe (unless the user
# already set the var), so the gnupg backend works with zero external install.
$cli = @'
@echo off
setlocal
if not defined FILEROUTER_GNUPG_BINARY set "FILEROUTER_GNUPG_BINARY=%~dp0gnupg\bin\gpg.exe"
"%~dp0python\python.exe" -m filerouter %*
'@
$doctor = @'
@echo off
setlocal
if not defined FILEROUTER_GNUPG_BINARY set "FILEROUTER_GNUPG_BINARY=%~dp0gnupg\bin\gpg.exe"
"%~dp0python\python.exe" -m filerouter.cli.doctor %*
'@
$svc = @'
@echo off
setlocal
if not defined FILEROUTER_GNUPG_BINARY set "FILEROUTER_GNUPG_BINARY=%~dp0gnupg\bin\gpg.exe"
"%~dp0python\python.exe" -m filerouter.service.windows %*
'@
Set-Content -Path (Join-Path $BundleDir "filerouter.bat")         -Value $cli    -Encoding ascii
Set-Content -Path (Join-Path $BundleDir "filerouter-doctor.bat")  -Value $doctor -Encoding ascii
Set-Content -Path (Join-Path $BundleDir "filerouter-service.bat") -Value $svc    -Encoding ascii

# -- 9. write the quick-start README ----------------------------------------
Write-Step "Writing README-PORTABLE.txt"
$readme = @"
FileRouter $AppVersion - version portable Windows x64
=====================================================

Bundle autonome : Python est embarque, AUCUNE installation requise.
Decompressez ce dossier ou vous voulez, puis ouvrez une invite (cmd ou
PowerShell) dans ce dossier.

COMPATIBILITE
  Windows x64 : Windows 10, Windows 11, et Windows Server 2016 / 2019 /
  2022 / 2025. Aucune dependance systeme a installer (l'Universal C Runtime
  requis est integre a toutes ces versions).

CONTENU
  python\                    Runtime Python embarque (+ FileRouter et deps)
  gnupg\bin\gpg.exe          GnuPG embarque (backend de chiffrement gnupg)
  config\config.example.yaml Modele de configuration commente (A COPIER)
  docs\                      Documentation complete (fr + en + schemas + exemples)
  README.md                  Presentation du projet (FR/EN)
  VERSIONS.txt               Versions exactes de toutes les dependances (suivi CVE)
  LICENSE
  filerouter.bat             CLI principale
  filerouter-doctor.bat      Diagnostic et reparation
  filerouter-service.bat     Gestion du service Windows natif

  100% AUTONOME : Python ET GnuPG sont embarques. Rien a installer.

DEMARRAGE RAPIDE
  1) Creez VOTRE config a partir du modele (a faire une seule fois) :
       copy config\config.example.yaml config\config.yaml
     puis editez config\config.yaml (repertoires metier, alias, regles).
     Astuce : vous pouvez aussi la placer hors du bundle, p.ex.
       C:\ProgramData\FileRouter\config.yaml

  2) Diagnostic + creation des repertoires :
       filerouter-doctor.bat --config config\config.yaml --fix --yes

  3) Validez la configuration :
       filerouter.bat --config config\config.yaml validate-config

  4) Lancez en avant-plan (Ctrl+C pour arreter) :
       filerouter.bat --config config\config.yaml run

AUTRES COMMANDES
  filerouter.bat --config config\config.yaml preview          # quels fichiers sont surveilles / traites (sans rien deplacer)
  filerouter.bat --config config\config.yaml preview --watched-only
  filerouter.bat --config config\config.yaml health
  filerouter.bat --config config\config.yaml list-quarantine
  filerouter.bat --config config\config.yaml reconcile
  filerouter.bat --config config\config.yaml trace <technical_id>

SERVICE WINDOWS NATIF (invite ADMINISTRATEUR requise)
  filerouter-service.bat install --config "%CD%\config\config.yaml"
  filerouter-service.bat start
  (plusieurs instances : ... install --instance siteA --config <chemin>)

  COMPTE DE SERVICE (recommande, requis pour acceder a des partages UNC) :
  le service tourne SOUS ce compte (pas LocalSystem). Le compte doit avoir le
  droit "Ouvrir une session en tant que service".
    filerouter-service.bat install --instance siteA ^
        --config "%CD%\config\config.yaml" ^
        --username "DOMAINE\svc_filerouter" --password "***" --startup auto

MISE A JOUR EN PLACE (sans rien casser ni ecraser la config)
  1) Arretez le service :  filerouter-service.bat stop  (ou ... stop --instance X)
  2) Decompressez la NOUVELLE archive dans le MEME dossier parent : le dossier
     "filerouter\" est mis a jour en place (python, gnupg, code). L'archive ne
     contient PAS config.yaml -> votre configuration n'est JAMAIS ecrasee
     (seul config\config.example.yaml, un modele, est rafraichi).
  3) Redemarrez le service :  filerouter-service.bat start
  Conseil : gardez runtime/exchange/trousseau HORS du dossier du bundle (ils le
  sont deja si vous suivez la config d'exemple) pour une mise a jour 100% sereine.

CHIFFREMENT OpenPGP
  - backend: pgpy   -> pur Python, fonctionne tel quel (aucun outil externe).
  - backend: gnupg  -> utilise le gpg.exe EMBARQUE (gnupg\bin\gpg.exe). Les
                       lanceurs .bat le selectionnent automatiquement via la
                       variable FILEROUTER_GNUPG_BINARY. Pour le SERVICE, fixez
                       plutot le chemin dans la config :
                         encryption:
                           backend: gnupg
                           gnupg_binary: <ce_dossier>\gnupg\bin\gpg.exe
                           gnupg_home:   <dossier_du_trousseau>
  - backend: noop   -> pas de chiffrement.

Documentation complete : dossier docs\ (docs\fr\ et docs\en\) livre dans ce bundle.
"@
Set-Content -Path (Join-Path $BundleDir "README-PORTABLE.txt") -Value $readme -Encoding utf8

# -- 10. zip it --------------------------------------------------------------
Write-Step "Creating $ZipPath"
Compress-Archive -Path $BundleDir -DestinationPath $ZipPath -Force
$sizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)

Write-Step "DONE"
Write-Host "    bundle : $BundleDir"
Write-Host "    zip    : $ZipPath ($sizeMB MB)"
