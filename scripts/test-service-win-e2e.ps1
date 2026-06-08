<#
.SYNOPSIS
    End-to-end test of the FileRouter native Windows service running under a
    DEDICATED service account, from the portable bundle.

.DESCRIPTION
    Exercises the full service lifecycle against the real Windows SCM:
      1. create a dedicated local service account (random password),
      2. grant it the "Log on as a service" right (SeServiceLogonRight, via LSA),
      3. install the FileRouter service to run AS that account,
      4. verify the service exists and its logon account is the dedicated one,
      5. start it, drop a business file, prove it gets routed to exchange_out
         (functional proof the service runs and works under that account),
      6. stop and remove the service,
      7. delete the account, the machine env var and the workspace.

    Cleanup runs in a finally block, so the service AND the account are always
    removed even if a step fails.

    REQUIRES an elevated (Administrator) PowerShell: creating a local account,
    granting a privilege and registering a service all need admin rights.

.PARAMETER BundleDir
    Path to the extracted portable bundle (folder containing filerouter-service.bat).
#>
[CmdletBinding()]
param(
    [string]$BundleDir = "C:\sources\fr-verify\filerouter",
    [string]$Account   = "svc_fr_e2e",
    [string]$Instance  = "e2eacct",
    [string]$Workspace = "C:\fr-svc-e2e"
)

# NB: "Continue", not "Stop" — in Windows PowerShell 5.1 a native command (our
# .bat) writing to stderr would otherwise raise a terminating error and mask the
# real output. We gate progress with explicit PASS/FAIL checks instead.
$ErrorActionPreference = "Continue"
$svcName = "FileRouter_$Instance"
$envVar  = "FILEROUTER_CONFIG_" + $Instance.ToUpper()
$pass    = $null
$created = $false
$fail    = $false

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    [PASS] $m" -ForegroundColor Green }
function Bad($m)  { $script:fail = $true; Write-Host "    [FAIL] $m" -ForegroundColor Red }

# -- admin gate --------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "This test must run elevated (Administrator)." }

# -- LSA helper: grant a privilege/right to an account (no external tools) ---
if (-not ("FrLsa" -as [type])) {
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Security.Principal;
public static class FrLsa {
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_UNICODE_STRING { public ushort Length; public ushort MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_OBJECT_ATTRIBUTES { public int Length; public IntPtr RootDirectory; public IntPtr ObjectName;
        public uint Attributes; public IntPtr SecurityDescriptor; public IntPtr SecurityQualityOfService; }
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern uint LsaOpenPolicy(ref LSA_UNICODE_STRING SystemName, ref LSA_OBJECT_ATTRIBUTES oa, uint access, out IntPtr handle);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern uint LsaAddAccountRights(IntPtr handle, byte[] sid, LSA_UNICODE_STRING[] rights, uint count);
    [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr handle);
    [DllImport("advapi32.dll")] static extern int LsaNtStatusToWinError(uint status);
    static LSA_UNICODE_STRING S(string s) {
        var u = new LSA_UNICODE_STRING();
        u.Buffer = Marshal.StringToHGlobalUni(s);
        u.Length = (ushort)(s.Length * 2);
        u.MaximumLength = (ushort)((s.Length + 1) * 2);
        return u;
    }
    public static void Grant(string account, string right) {
        var sid = (SecurityIdentifier)(new NTAccount(account)).Translate(typeof(SecurityIdentifier));
        byte[] b = new byte[sid.BinaryLength]; sid.GetBinaryForm(b, 0);
        var sys = new LSA_UNICODE_STRING(); var oa = new LSA_OBJECT_ATTRIBUTES();
        IntPtr h; uint st = LsaOpenPolicy(ref sys, ref oa, 0x000F0FFF, out h);
        if (st != 0) throw new Exception("LsaOpenPolicy=" + LsaNtStatusToWinError(st));
        try {
            var r = new LSA_UNICODE_STRING[] { S(right) };
            st = LsaAddAccountRights(h, b, r, 1);
            if (st != 0) throw new Exception("LsaAddAccountRights=" + LsaNtStatusToWinError(st));
        } finally { LsaClose(h); }
    }
}
"@
}

try {
    $svcBat = Join-Path $BundleDir "filerouter-service.bat"
    if (-not (Test-Path $svcBat)) { throw "bundle launcher not found: $svcBat" }

    # -- 1. dedicated local service account ---------------------------------
    Step "Creating dedicated service account '$Account'"
    Get-LocalUser -Name $Account -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-LocalUser -Name $Account }   # idempotent start
    # Build a strong password from a cmd-safe alphabet (no % & ^ " | < > space),
    # so the .bat's %* forwarding to python never mangles it.
    $safe = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789".ToCharArray()
    $pass = (-join (1..24 | ForEach-Object { $safe | Get-Random })) + "Aa9#-_"
    $sec  = ConvertTo-SecureString $pass -AsPlainText -Force
    New-LocalUser -Name $Account -Password $sec -FullName "FileRouter E2E svc" `
        -Description "Temporary FileRouter service e2e account" `
        -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    $created = $true
    Ok "account created"

    # -- 2. grant "Log on as a service" -------------------------------------
    Step "Granting SeServiceLogonRight to '$Account'"
    [FrLsa]::Grant("$env:COMPUTERNAME\$Account", "SeServiceLogonRight")
    Ok "right granted"

    # -- 3. workspace + minimal config + NTFS access for the account --------
    Step "Preparing workspace + config at $Workspace"
    if (Test-Path $Workspace) { Remove-Item -LiteralPath $Workspace -Recurse -Force }
    $biz = Join-Path $Workspace "business\TESTAL"
    New-Item -ItemType Directory -Force -Path $biz | Out-Null
    $cfgPath = Join-Path $Workspace "config.yaml"
    @"
instance: { site: E2E, role: both, workers: 1 }
base_folders:
  - { alias: TESTAL, path: $Workspace\business\TESTAL }
mappings:
  flows:   { TESTAL: TESTFLOW }
  routing: { TESTAL: REMOTE }
exchange: { out: $Workspace\exchange_out, in: $Workspace\exchange_in }
runtime:  { root: $Workspace\runtime }
naming:
  pattern: "{flow}_{direction}_{timestamp}_{technical_id}.{extension}"
  timestamp_format: "%Y%m%dT%H%M%S"
  technical_id_strategy: ulid
  meta_suffix: ".meta.json"
hashing: { algorithm: SHA-256, chunk_size_bytes: 65536, verify_inbound: true }
encryption: { backend: noop, require_signature_inbound: false, rules: [] }
inclusion: { patterns: ["**/*"] }
exclusion: { patterns: ["**/*.tmp"] }
duplicates: { outbound_policy: skip, inbound_policy: skip }
archival: { source_policy: archive, archive_layout: "%Y/%m/%d" }
retention: { archive_days: 30, audit_days: 365, logs_days: 90, error_days: 0 }
scanning: { interval_seconds: 1, stability_checks: 1, stability_interval_seconds: 0.2, pair_grace_period_seconds: 5 }
locking: { lock_ttl_seconds: 300, heartbeat_interval_seconds: 30 }
logging: { format: jsonl, streams: {} }
"@ | Set-Content -Path $cfgPath -Encoding ascii
    # grant the service account full control over the workspace, and
    # read/execute over the bundle (so it can run python.exe + import filerouter)
    icacls $Workspace /grant "${Account}:(OI)(CI)F" /T /C /Q | Out-Null
    icacls $BundleDir /grant "${Account}:(OI)(CI)RX" /T /C /Q | Out-Null
    Ok "workspace ready, account granted access"

    # -- 4. install the service to run AS the dedicated account -------------
    Step "Installing service '$svcName' as .\$Account"
    $installOut = & $svcBat install --instance $Instance --config $cfgPath `
        --username ".\$Account" --password $pass --startup manual 2>&1
    $installOut | ForEach-Object { Write-Host "    | $_" }
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if ($svc) { Ok "service registered" } else { Bad "service NOT registered"; throw "install failed" }

    $startName = (Get-CimInstance Win32_Service -Filter "Name='$svcName'").StartName
    Write-Host "    logon account = $startName"
    if ($startName -match [regex]::Escape($Account)) { Ok "runs under the dedicated account" }
    else { Bad "service logon account is '$startName', expected one containing '$Account'" }

    # -- 5. start + functional routing proof --------------------------------
    Step "Starting service and verifying it routes a file"
    $probe = Join-Path $biz "probe.csv"
    "id;amount`n1;100" | Set-Content -Path $probe -Encoding ascii
    Start-Service -Name $svcName
    Start-Sleep -Seconds 2
    $svc = Get-Service -Name $svcName
    if ($svc.Status -eq "Running") { Ok "service is Running" } else { Bad "service status = $($svc.Status)" }

    $outDir = Join-Path $Workspace "exchange_out"
    $routed = $false
    foreach ($i in 1..20) {
        if ((Test-Path $outDir) -and (Get-ChildItem $outDir -File -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -notlike "*.meta.json" })) { $routed = $true; break }
        Start-Sleep -Seconds 1
    }
    if ($routed) {
        $payload = Get-ChildItem $outDir -File | Where-Object { $_.Name -notlike "*.meta.json" } | Select-Object -First 1
        Ok "file routed to exchange_out: $($payload.Name)"
    } else { Bad "no file was routed within 20s (service may not be working as the account)" }

    # -- 6. stop + remove ---------------------------------------------------
    Step "Stopping and removing the service"
    Stop-Service -Name $svcName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    & $svcBat remove --instance $Instance
    Start-Sleep -Seconds 1
    if (Get-Service -Name $svcName -ErrorAction SilentlyContinue) { Bad "service still present after remove" }
    else { Ok "service removed" }
}
finally {
    # -- 7. guaranteed cleanup ----------------------------------------------
    Step "Cleanup"
    Stop-Service -Name $svcName -Force -ErrorAction SilentlyContinue
    & (Join-Path $BundleDir "filerouter-service.bat") remove --instance $Instance 2>$null | Out-Null
    if (Get-Service -Name $svcName -ErrorAction SilentlyContinue) {
        sc.exe delete $svcName | Out-Null   # last-resort removal
    }
    [Environment]::SetEnvironmentVariable($envVar, $null, "Machine")
    icacls $BundleDir /remove $Account /T /C /Q 2>$null | Out-Null  # drop the temp grant
    if ($created) {
        Remove-LocalUser -Name $Account -ErrorAction SilentlyContinue
        Write-Host "    removed account '$Account'"
    }
    if (Test-Path $Workspace) {
        Remove-Item -LiteralPath $Workspace -Recurse -Force -ErrorAction SilentlyContinue
    }
    $svcGone = -not (Get-Service -Name $svcName -ErrorAction SilentlyContinue)
    $accGone = -not (Get-LocalUser -Name $Account -ErrorAction SilentlyContinue)
    Write-Host "    service removed: $svcGone | account removed: $accGone"
}

Write-Host ""
if ($fail) { Write-Host "SERVICE E2E: FAILED" -ForegroundColor Red; exit 1 }
else       { Write-Host "SERVICE E2E: PASSED" -ForegroundColor Green; exit 0 }
