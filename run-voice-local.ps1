# Athena's voice-mode chat server on this laptop, for talk.py while the GPU box isn't reachable.
# Same as run-local-qwen.ps1 (qwen in Ollama, hybrid search + reranker), plus /api/stt and /api/tts
# (Whisper in, Kokoro out, with the X-Mouth lip-sync timing the display needs).
#
# The 6 GB GPU holds qwen and the reranker and nothing more, so Whisper and Kokoro run on the CPU.
# The server code is the voice branch's copy in D:\athena-autotune; the packages are the main venv's.
#
#   powershell -ExecutionPolicy Bypass -File run-voice-local.ps1
#   then, in another window:  D:\athena-face-venv\Scripts\python.exe talk.py --sprite snoopy-sprite.png
param([int]$Port = 3040, [string]$Whisper = "small.en")

$ollama = "http://localhost:11434"
$model = "qwen3:4b-instruct"
$web = "D:\athena-autotune\CMKL-Athena\onyx\web"
$py = "D:\OneDrive\Documents\New_Life\Athena\CMKL-Athena\.venv\Scripts\python.exe"

$env:LLM_PROVIDER = "groq"                      # the OpenAI-compatible route, pointed at Ollama
$env:GROQ_BASE_URL = "$ollama/v1"
$env:GROQ_API_KEY = "ollama"
$env:GROQ_MODEL = $model
$env:LLM_REASONING = ""
$env:SEARCH = "hybrid"
$env:RERANK_DEPTH = "20"
$env:PROMPT = "v4"
$env:PROMPT_LOW = "v5"
$env:PROMPT_ROUTE_BELOW = "-2"
$env:LLM_TEMPERATURE = "0"
$env:HF_HOME = "D:\hf-cache"                    # C: is nearly full
$env:PYTHONIOENCODING = "utf-8"
$env:RATE_LIMIT = "1000"
# Not VOICE_PRELOAD: loading Kokoro while the reranker loads breaks Kokoro's transformers import
# ("cannot import name 'AlbertModel"), and the server never retries. The voice is warmed up below instead.
$env:VOICE_PRELOAD = "0"
$env:STT_DEVICE = "cpu"
$env:STT_MODEL = $Whisper
$env:TTS_DEVICE = "cpu"

# Ollama has to be running before qwen can be loaded
try { Invoke-RestMethod "$ollama/api/version" | Out-Null } catch {
    Write-Host "Starting Ollama..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    do { Start-Sleep 1; try { $up = Invoke-RestMethod "$ollama/api/version" } catch { $up = $null } } until ($up)
}

$server = Start-Process $py -ArgumentList "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", $Port `
    -WorkingDirectory $web -NoNewWindow -PassThru
Write-Host "Loading the handbook pages, the reranker, Whisper and Kokoro..."
do {
    Start-Sleep 3
    try { $h = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" } catch { $h = $null }
} until (($h -and $h.mode -eq "local") -or $server.HasExited)
if ($server.HasExited) { Write-Host "The chat server stopped; see the errors above."; exit 1 }

# qwen after the reranker, so it gets the GPU memory that is left, and kept loaded
Invoke-RestMethod "$ollama/api/generate" -Method Post -Body (@{model = $model; keep_alive = 0} | ConvertTo-Json) | Out-Null
Invoke-RestMethod "$ollama/api/generate" -Method Post -Body (@{model = $model; keep_alive = -1; prompt = "hi"; stream = $false;
    options = @{num_predict = 1}} | ConvertTo-Json) | Out-Null
ollama ps

Write-Host "Warming up Athena's voice (Kokoro)..."
try {
    Invoke-WebRequest "http://127.0.0.1:$Port/api/tts" -Method Post -ContentType "application/json" `
        -Body '{"text": "Hello."}' -UseBasicParsing | Out-Null
} catch { Write-Host "  The voice didn't load: $((Invoke-RestMethod "http://127.0.0.1:$Port/api/health").voice_error.tts)" }
Write-Host "Ready on http://127.0.0.1:$Port  (PROCESSOR should say 100% GPU). Now run talk.py; Ctrl+C here stops the server."
Wait-Process -Id $server.Id
