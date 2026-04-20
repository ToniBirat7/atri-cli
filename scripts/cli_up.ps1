param(
    [string]$InstallerUrl = "https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/scripts/install_cli.py"
)

$ErrorActionPreference = "Stop"
$commandName = if ($env:TARBAR_COMMAND_NAME) { $env:TARBAR_COMMAND_NAME } else { "tarbar" }

$python = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue)
}

if (-not $python) {
    Write-Error "[cli-up] ERROR: Python is required (py or python)."
}

$response = Invoke-WebRequest -Uri $InstallerUrl -UseBasicParsing
$script = $response.Content
if (-not $script) {
    Write-Error "[cli-up] ERROR: Failed to download installer script."
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

$launcher = Join-Path $HOME ".local/bin/$commandName"
if (Get-Command $commandName -ErrorAction SilentlyContinue) {
    & $commandName @args
} elseif (Test-Path $launcher) {
    & $launcher @args
} else {
    Write-Error "[cli-up] Installed, but launcher '$commandName' was not found. Add ~/.local/bin to PATH and run $commandName."
}
