# One command for local Athena: the voice server (Ollama + qwen + search + Whisper + Kokoro) and talk.py.
#
#   powershell -ExecutionPolicy Bypass -File athena.ps1                 # or just: athena.cmd
#   powershell -ExecutionPolicy Bypass -File athena.ps1 --type          # extra arguments go to talk.py
#   powershell -ExecutionPolicy Bypass -File athena.ps1 --display off
#
# It stops any old server on the port first (a half-broken one is never reused), checks the models are
# where Ollama looks, reports low RAM (the biggest slowdown here), starts run-voice-local.ps1 in the
# background with its output in server.log, waits until the search, Whisper and Kokoro are all loaded,
# then runs talk.py in this window. Ctrl+C quits talk.py and stops the server it started.
[CmdletBinding(PositionalBinding = $false)]
param(
    [int]$Port = 3040,
    [string]$Whisper = "small.en",
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$TalkArgs
)

$here = $PSScriptRoot
$faceVenv = "D:\athena-face-venv\Scripts\python.exe"
$log = Join-Path $here "server.log"
$ready = Join-Path $here "server.ready"
$model = "qwen3:4b-instruct"

function Stop-Tree($procId) { & taskkill /PID $procId /T /F 2>&1 | Out-Null }

# --- 1. old server and old talk.py out of the way
$old = @()
$old += Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
$old += Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "talk\.py" } | Select-Object -ExpandProperty ProcessId
foreach ($id in ($old | Sort-Object -Unique)) {
    Write-Host "Stopping the old Athena process $id..."
    Stop-Tree $id
}
Remove-Item $ready -ErrorAction SilentlyContinue

# --- 2. the pieces we need are there
if (-not (Test-Path $faceVenv)) { Write-Host "Missing $faceVenv (talk.py's Python)."; exit 1 }
$ollamaModels = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
if ($ollamaModels) { $env:OLLAMA_MODELS = $ollamaModels }       # so an Ollama we start sees the same folder
try { $have = (Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 3).models.name } catch { $have = $null }
if ($null -ne $have -and $have -notcontains $model) {
    Write-Host "Ollama is running but doesn't have $model (OLLAMA_MODELS = $ollamaModels)."
    Write-Host "If the models are still in C:\Users\$env:USERNAME\.ollama\models, copy them and restart Ollama:"
    Write-Host "  robocopy C:\Users\$env:USERNAME\.ollama\models $ollamaModels /E"
    exit 1
}

# --- 3. RAM: paging is what made search 5x slower on Nov 2-4 (data/latency.csv)
$os = Get-CimInstance Win32_OperatingSystem
$freeGB = $os.FreePhysicalMemory / 1MB
Write-Host ("Free RAM: {0:N1} GB of {1:N1} GB" -f $freeGB, ($os.TotalVisibleMemorySize / 1MB))
if ($freeGB -lt 4) {
    Write-Host "  That's low; Athena will be slow while Windows pages. Close what you don't need. Biggest right now:"
    Get-Process | Where-Object { $_.Name -notmatch "^(python|ollama|System|Memory Compression|MsMpEng|svchost)" } |
        Group-Object Name | ForEach-Object { [pscustomobject]@{ App = $_.Name; MB = [int](($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1MB) } } |
        Sort-Object MB -Descending | Select-Object -First 6 | ForEach-Object { Write-Host ("    {0,-18} {1,5} MB" -f $_.App, $_.MB) }
}

# --- 4. the server, in the background; its output goes to server.log
Write-Host "Starting the Athena server (about a minute); log: $log"
$server = Start-Process powershell -PassThru -WindowStyle Hidden -RedirectStandardOutput $log `
    -RedirectStandardError "$log.err" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $here "run-voice-local.ps1"),
                  "-Port", $Port, "-Whisper", $Whisper

$failed = $null
$deadline = (Get-Date).AddMinutes(6)
$wait = [Diagnostics.Stopwatch]::StartNew()
while (-not (Test-Path $ready)) {
    if ($server.HasExited) { $failed = "The server script stopped."; break }
    if ((Get-Date) -gt $deadline) { $failed = "The server didn't get ready in 6 minutes."; break }
    try { $h = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 } catch { $h = $null }
    if ($h -and $h.kb_error) { $failed = "The search failed to load: " + ($h.kb_error -split "`n")[0]; break }
    Write-Host ("`r  loading... {0:N0} s" -f $wait.Elapsed.TotalSeconds) -NoNewline
    Start-Sleep 2
}
Write-Host ""
if ($failed) {
    Write-Host $failed
    if ($failed -match "CUDA") { Write-Host "The GPU is in a bad state. Reboot (or reset the GPU driver: Win+Ctrl+Shift+B), then run this again." }
    Write-Host "Last lines of $log :"
    Get-Content $log, "$log.err" -Tail 12 -ErrorAction SilentlyContinue
    Stop-Tree $server.Id
    exit 1
}
Write-Host ("Ready after {0:N0} s." -f $wait.Elapsed.TotalSeconds)
try { $h = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 5; Write-Host "  $($h.mode): $($h.llm), $($h.search)" } catch {}

# --- 5. talk.py here; leaving it stops the server
Push-Location $here
try {
    $talk = @("talk.py")
    # the live fox by default; pass --sprite snoopy-sprite.png for Snoopy
    $talk += $TalkArgs
    & $faceVenv @talk
} finally {
    Pop-Location
    Write-Host "Stopping the Athena server..."
    Stop-Tree $server.Id
    Remove-Item $ready -ErrorAction SilentlyContinue
}
