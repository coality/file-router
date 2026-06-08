# =============================================================================
# transport.ps1 — simulate the EXTERNAL transport between two FileRouter sites.
#
# FileRouter does NOT move files across sites; an external mechanism does. On a
# single machine this script plays that role: it copies each complete (payload +
# .meta.json) pair from Site A's exchange_out to Site B's exchange_in, in a loop.
#
# The payload is moved FIRST and its metadata LAST, so Site B never sees metadata
# pointing at a missing payload. Already-moved files simply disappear from the
# source, so the loop is naturally idempotent.
#
# Usage (PowerShell):
#   .\transport.ps1
#   .\transport.ps1 -Source C:\SiteA\exchange_out -Dest C:\SiteB\exchange_in -IntervalSeconds 2
# Stop with Ctrl+C.
# =============================================================================

param(
    [string]$Source = "C:\SiteA\exchange_out",
    [string]$Dest = "C:\SiteB\exchange_in",
    [int]$IntervalSeconds = 2
)

# Ensure the destination exists (Site B also creates it at startup).
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Write-Host "Transport running: $Source  ->  $Dest  (every ${IntervalSeconds}s). Ctrl+C to stop."

while ($true) {
    # Drive the loop from metadata files: each one names a complete pair.
    Get-ChildItem -Path $Source -Filter *.meta.json -ErrorAction SilentlyContinue |
        ForEach-Object {
            $metaPath = $_.FullName
            # The payload shares the name without the ".meta.json" suffix.
            $payloadPath = $metaPath.Substring(0, $metaPath.Length - ".meta.json".Length)

            if (Test-Path -LiteralPath $payloadPath) {
                try {
                    # Move payload first, then metadata (metadata published last).
                    Move-Item -LiteralPath $payloadPath -Destination $Dest -Force
                    Move-Item -LiteralPath $metaPath -Destination $Dest -Force
                    Write-Host "moved: $([System.IO.Path]::GetFileName($payloadPath))"
                }
                catch {
                    # A transient lock (file still being written) -> retry next tick.
                    Write-Host "retry later: $($_.Exception.Message)"
                }
            }
        }

    Start-Sleep -Seconds $IntervalSeconds
}
