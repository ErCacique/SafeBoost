<#
.SYNOPSIS
  Comprueba en Windows que los store_id de appx_reinstall (data/tweaks.json) existen en
  Microsoft Store y corresponden a la app esperada. Solo lee: no instala nada.

.EXAMPLE
  pwsh -File scripts/verify_store_ids.ps1
#>
$ErrorActionPreference = 'Stop'
$catalog = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot '..\data\tweaks.json') | ConvertFrom-Json
$failed = 0
foreach ($tweak in $catalog.tweaks) {
    foreach ($op in $tweak.revert | Where-Object { $_.op -eq 'appx_reinstall' }) {
        if (-not $op.store_id) {
            $hit = winget search --name $op.store_name --source msstore --accept-source-agreements 2>$null |
                Select-String -SimpleMatch $op.store_name
            $status = if ($hit) { "SIN ID · candidato: $($hit.Line.Trim())" } else { 'SIN ID · no encontrado' }
            Write-Host ("{0,-28} {1}" -f $tweak.id, $status) -ForegroundColor Yellow
            continue
        }
        $out = winget show --id $op.store_id --source msstore --accept-source-agreements 2>$null | Out-String
        if ($LASTEXITCODE -eq 0 -and $out -match [regex]::Escape($op.store_name.Split(' ')[0])) {
            Write-Host ("{0,-28} OK  {1} ({2})" -f $tweak.id, $op.store_id, $op.store_name) -ForegroundColor Green
        } else {
            Write-Host ("{0,-28} ERROR {1}: no coincide con '{2}'" -f $tweak.id, $op.store_id, $op.store_name) -ForegroundColor Red
            $failed++
        }
    }
}
exit $failed
