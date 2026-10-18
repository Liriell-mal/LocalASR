param([int]$Port = 8765, [string]$DataDir = "", [switch]$NoBrowser, [switch]$Stop, [ValidateSet('independent')][string]$Runtime = 'independent')
$ErrorActionPreference = 'Stop'
# Optional entry point when the existing Windows policy allows scripts.
# No ExecutionPolicy override; Start LocalASR.cmd works under Restricted.
$configPath = 'runtime\independent\local.json'
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot $configPath) -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $config.python -PathType Leaf)) { throw 'Python local approuve absent. Aucun telechargement automatique.' }
$launchArguments = @('-I', '-B', '-S', (Join-Path $PSScriptRoot 'launch.py'), '--runtime', $Runtime, '--port', $Port)
if ($DataDir) { $launchArguments += @('--data-dir', $DataDir) }
if ($NoBrowser) { $launchArguments += '--no-browser' }
if ($Stop) { $launchArguments += '--stop' }
& $config.python @launchArguments
exit $LASTEXITCODE
