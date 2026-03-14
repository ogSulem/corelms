param(
  [Parameter(Mandatory=$true)][string]$PublicUrl,
  [Parameter(Mandatory=$true)][string]$S3Remote,
  [string]$RcloneExePath = "",
  [int]$Limit = 200,
  [string]$StateFile = ".yadisk_public_to_s3.state.json",
  [string]$FailedFile = ".yadisk_public_to_s3.failed.txt",
  [switch]$AppendFailedFile,
  [int]$MaxAttempts = 5,
  [int]$RetrySleepSeconds = 20,
  [switch]$ContinueOnError,
  [switch]$SkipExisting,
  [string[]]$ExcludeModules = @(),
  [bool]$VerifyAfterUpload = $true
)

$ErrorActionPreference = "Stop"

$script:RcloneExe = $null

function UrlEncode([string]$s) {
  return [uri]::EscapeDataString($s)
}

function Sanitize([string]$s) {
  $t = ($s -replace '[\\/:*?"<>|]', '_')
  $t = ($t -replace '\s+', ' ').Trim()
  if (-not $t) { $t = "item" }
  return $t
}

function Slugify([string]$s) {
  # Mirrors backend slugify for S3 segments: allow latin + cyrillic, collapse spaces to '-', trim, max 80.
  $t = [string]$s
  if ($null -eq $t) { $t = "" }
  $t = $t.Trim().ToLowerInvariant()
  if ($t.EndsWith(".zip")) { $t = $t.Substring(0, $t.Length - 4) }
  $t = ($t -replace '\s+', ' ').Trim()
  # Unicode-safe: keep letters/digits from any alphabet + '-', '_', '.', spaces.
  # This avoids encoding glitches in regex literals on Windows PowerShell 5.1.
  $t = ($t -replace '[^\p{L}\p{Nd}\-_. ]+', '-')
  $t = $t.Replace(' ', '-')
  $t = ($t -replace '-+', '-')
  $t = $t.Trim('-','_','.')
  if (-not $t) { $t = "module" }
  if ($t.Length -gt 80) { $t = $t.Substring(0, 80) }
  return $t
}

function GetPublicResource([string]$publicUrl, [string]$path = "", [int]$limit = 200, [int]$offset = 0) {
  $publicEnc = UrlEncode $publicUrl
  $base = "https://cloud-api.yandex.net/v1/disk/public/resources"
  if ($path) {
    $pathEnc = UrlEncode $path
    $url = ($base + "?public_key=" + $publicEnc + "&path=" + $pathEnc + "&limit=" + $limit + "&offset=" + $offset)
  } else {
    $url = ($base + "?public_key=" + $publicEnc + "&limit=" + $limit + "&offset=" + $offset)
  }
  return Invoke-RestMethod -Uri $url -Method Get
}

function GetDownloadHref([string]$publicUrl, [string]$path) {
  $publicEnc = UrlEncode $publicUrl
  $pathEnc = UrlEncode $path
  $url = ("https://cloud-api.yandex.net/v1/disk/public/resources/download" + "?public_key=" + $publicEnc + "&path=" + $pathEnc)
  $dl = Invoke-RestMethod -Uri $url -Method Get
  return [string]$dl.href
}

function ListAllItems([string]$publicUrl, [string]$path) {
  $all = @()
  $offset = 0
  while ($true) {
    $res = GetPublicResource -publicUrl $publicUrl -path $path -limit $Limit -offset $offset
    $items = @()
    try { $items = $res._embedded.items } catch { $items = @() }
    if (-not $items -or $items.Count -eq 0) { break }
    $all += $items
    if ($items.Count -lt $Limit) { break }
    $offset += $Limit
  }
  return $all
}

function EnsureRclone() {
  if ($script:RcloneExe) { return }

  $candidates = @()

  if ($RcloneExePath) {
    $candidates += $RcloneExePath
  }
  if ($env:RCLONE_EXE) {
    $candidates += $env:RCLONE_EXE
  }

  $cmd = Get-Command rclone -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Path) {
    $candidates += $cmd.Path
  }

  # Common locations (your setup looks like D:\rclone\rclone.exe)
  $candidates += "D:\rclone\rclone.exe"
  $candidates += "C:\rclone\rclone.exe"
  try {
    $candidates += (Join-Path $PSScriptRoot "rclone.exe")
  } catch { }

  foreach ($p in $candidates) {
    try {
      if (-not $p) { continue }
      $pp = [string]$p
      if (Test-Path -LiteralPath $pp) {
        $script:RcloneExe = $pp
        return
      }
    } catch {
      continue
    }
  }

  throw "rclone.exe not found. Provide -RcloneExePath 'D:\\rclone\\rclone.exe' or add rclone to PATH."
}

function UploadZip([string]$href, [string]$dst) {
  Write-Host "Uploading to S3: '$dst'"
  & $script:RcloneExe copyurl $href "$dst" --no-traverse --progress --stats 30s --stats-one-line --timeout 30m --contimeout 2m --retries 10 --low-level-retries 20 --retries-sleep 10s --transfers 1 --checkers 1 --s3-upload-cutoff 1M --s3-chunk-size 64M --s3-upload-concurrency 1
  if ($LASTEXITCODE -ne 0) {
    throw "rclone copyurl failed with exit code $LASTEXITCODE"
  }
}

function GetHrefContentLength([string]$href) {
  try {
    # Yandex public download links can return different Content-Length for HEAD vs GET.
    # Prefer a ranged GET (1 byte) and parse Content-Range total size.
    try {
      $resp2 = Invoke-WebRequest -Uri $href -Method Get -UseBasicParsing -Headers @{ "Accept-Encoding" = "identity"; "Range" = "bytes=0-0" }
      $cr = $resp2.Headers["Content-Range"]
      if ($cr) {
        $m = [regex]::Match([string]$cr, '/(?<total>\d+)$')
        if ($m.Success) {
          $t = [int64]$m.Groups['total'].Value
          if ($t -gt 0) { return $t }
        }
      }
    } catch {
      # ignore and fallback to HEAD
    }

    $resp = Invoke-WebRequest -Uri $href -Method Head -UseBasicParsing -Headers @{ "Accept-Encoding" = "identity" }
    $cl = $resp.Headers["Content-Length"]
    if (-not $cl) { return $null }
    $v = [int64]$cl
    if ($v -le 0) { return $null }
    return $v
  } catch {
    return $null
  }
}

function DeleteDst([string]$dst) {
  try {
    & $script:RcloneExe deletefile $dst --no-traverse 2>$null
  } catch {
  }
}

function UploadZipWithFreshHref([string]$publicUrl, [string]$dirPath, [string]$dst, [int]$maxAttempts, [int]$retrySleepSeconds) {
  $lastErr = $null
  for ($i = 1; $i -le $maxAttempts; $i += 1) {
    try {
      $href = GetDownloadHref -publicUrl $publicUrl -path $dirPath
      $expectedSize = GetHrefContentLength -href $href
      UploadZip -href $href -dst $dst
      if ($VerifyAfterUpload) {
        if ($expectedSize -ne $null) {
          $st = GetDstStat -dst $dst
          if (-not $st -or $st.Size -eq $null) {
            throw "dst stat missing"
          }
          $dstSize = [int64]$st.Size
          if ($dstSize -ne $expectedSize) {
            DeleteDst -dst $dst
            throw "dst size mismatch (dst=$dstSize expected=$expectedSize)"
          }
        }
      }
      return
    } catch {
      $lastErr = $_
      Write-Host "Attempt $i/$maxAttempts failed for: $dst"
      try { Write-Host $lastErr.Exception.Message } catch { }
      if ($i -lt $maxAttempts) {
        Start-Sleep -Seconds $retrySleepSeconds
      }
    }
  }
  throw $lastErr
}

function LoadState([string]$path) {
  $s = @{}
  if (Test-Path -LiteralPath $path) {
    try {
      $raw = Get-Content -LiteralPath $path -Raw
      if ($raw) {
        $obj = $raw | ConvertFrom-Json
        foreach ($k in $obj.PSObject.Properties.Name) {
          $v = $obj.$k
          if ($v -is [bool]) {
            $s[$k] = @{
              ok = [bool]$v
            }
          } else {
            $t = @{}
            try {
              foreach ($pk in $v.PSObject.Properties.Name) {
                $t[$pk] = $v.$pk
              }
            } catch {
            }
            if (-not $t.ContainsKey('ok')) { $t['ok'] = $false }
            $s[$k] = $t
          }
        }
      }
    } catch {
      # ignore state parse errors
    }
  }
  return $s
}

function SaveState([string]$path, $state) {
  try {
    ($state | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $path -Encoding UTF8
  } catch {
    # ignore
  }
}

function RecordFailure([string]$failedFile, [string]$moduleName, [string]$dst, [string]$message) {
  try {
    $line = (Get-Date -Format "s") + "\t" + $moduleName + "\t" + $dst + "\t" + $message
    Add-Content -LiteralPath $failedFile -Value $line -Encoding UTF8
  } catch {
    # ignore
  }
}

function GetDstStat([string]$dst) {
  try {
    $raw = & $script:RcloneExe lsjson $dst --stat 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    if (-not $raw) { return $null }
    return ($raw | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function DstExists([string]$dst) {
  $st = GetDstStat -dst $dst
  if (-not $st) { return $false }
  if ($st.Size -eq $null) { return $false }
  if ([int64]$st.Size -lt 0) { return $false }
  return $true
}

# Defaults
if (-not $PSBoundParameters.ContainsKey('SkipExisting')) {
  $SkipExisting = $true
}

if ($null -eq $VerifyAfterUpload) { $VerifyAfterUpload = $true }

EnsureRclone

Write-Host "PublicUrl: $PublicUrl"
Write-Host "S3Remote: $S3Remote"
Write-Host "RcloneExe: $script:RcloneExe"
Write-Host "SkipExisting: $SkipExisting"
Write-Host "StateFile: $StateFile"
Write-Host "FailedFile: $FailedFile"

if ($FailedFile) {
  if (-not $AppendFailedFile) {
    try { Set-Content -LiteralPath $FailedFile -Value "" -Encoding UTF8 } catch { }
  }
}

$state = LoadState -path $StateFile

$root = GetPublicResource -publicUrl $PublicUrl -limit $Limit -offset 0
$rootDirs = @()
try { $rootDirs = $root._embedded.items | Where-Object { $_.type -eq "dir" } } catch { $rootDirs = @() }
if (-not $rootDirs -or $rootDirs.Count -eq 0) {
  throw "No directories found at root. Expected module folders."
}

$uploaded = 0
$skipped = 0
$failed = 0

foreach ($d in $rootDirs) {
  $dirName = Sanitize([string]$d.name)
  $dirPath = [string]$d.path
  $safe = Slugify $dirName

  if ($ExcludeModules) {
    $excluded = $false
    foreach ($pat in $ExcludeModules) {
      if (-not $pat) { continue }
      if ($dirName -like $pat) { $excluded = $true; break }
    }
    if ($excluded) {
      Write-Host "SKIP (excluded): $dirName"
      $skipped += 1
      continue
    }
  }

  $dstName = "$dirName.zip"
  $dst = "$S3Remote/uploads/$dstName"
  $stateKey = "uploads/$dstName"

  Write-Host "=== MODULE: $dirName => $stateKey ==="

  if ($state.ContainsKey($stateKey) -and $state[$stateKey] -and $state[$stateKey].ok) {
    if (DstExists -dst $dst) {
      Write-Host "SKIP (state): $dst"
      $skipped += 1
      continue
    }
    $state.Remove($stateKey) | Out-Null
    SaveState -path $StateFile -state $state
  }

  if ($SkipExisting) {
    if (DstExists -dst $dst) {
      $stat = GetDstStat -dst $dst
      Write-Host "SKIP (exists in S3): $dst (size=$($stat.Size))"
      $state[$stateKey] = @{
        ok = $true
        dst_size = [int64]$stat.Size
      }
      SaveState -path $StateFile -state $state
      $skipped += 1
      continue
    }
  }

  try {
    UploadZipWithFreshHref -publicUrl $PublicUrl -dirPath $dirPath -dst $dst -maxAttempts $MaxAttempts -retrySleepSeconds $RetrySleepSeconds
    $uploaded += 1
    $st2 = GetDstStat -dst $dst
    $state[$stateKey] = @{
      ok = $true
      dst_size = $(if ($st2 -and $st2.Size -ne $null) { [int64]$st2.Size } else { $null })
    }
    SaveState -path $StateFile -state $state
  } catch {
    $msg = ""
    try { $msg = [string]$_.Exception.Message } catch { $msg = "error" }
    Write-Host "FAILED: $dst"
    Write-Host $_
    if ($FailedFile) {
      RecordFailure -failedFile $FailedFile -moduleName $dirName -dst $dst -message $msg
    }
    $failed += 1
    if (-not $ContinueOnError) { throw }
  }
}

Write-Host "DONE. Uploaded: $uploaded; Skipped: $skipped; Failed: $failed"
