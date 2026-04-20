param(
    [string]$BootstrapUrl = "https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/web/scripts/local_up.py"
)

$ErrorActionPreference = "Stop"

$python = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue)
}

if (-not $python) {
    Write-Error "[local-up] ERROR: Python is required (py or python)."
}

$response = Invoke-WebRequest -Uri $BootstrapUrl -UseBasicParsing
$script = $response.Content
if (-not $script) {
    Write-Error "[local-up] ERROR: Failed to download bootstrap script."
}

$tmp = [System.IO.Path]::GetTempFileName()
Set-Content -Path $tmp -Value $script -Encoding UTF8

try {
    if ($python.Name -eq "py") {
        & py $tmp @args
    } else {
        & python $tmp @args
    }
}
finally {
    Remove-Item -Force $tmp -ErrorAction SilentlyContinue
}
