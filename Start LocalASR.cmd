@echo off
setlocal DisableDelayedExpansion
set "LOCALASR_LAUNCH_ROOT=%~dp0"
if not defined LOCALASR_PYTHON (
  for /f "usebackq delims=" %%P in (`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -NonInteractive -Command "$ErrorActionPreference = 'Stop'; try { $config = ConvertFrom-Json -InputObject (Get-Content -LiteralPath (Join-Path $env:LOCALASR_LAUNCH_ROOT 'runtime\independent\local.json') -Raw -Encoding UTF8); if ($config.python -isnot [string] -or [string]::IsNullOrWhiteSpace($config.python)) { exit 1 }; [Console]::WriteLine($config.python) } catch { exit 1 }"`) do set "LOCALASR_PYTHON=%%P"
)
if not defined LOCALASR_PYTHON (
  echo Configuration Python absente ou invalide : runtime\independent\local.json.
  echo Voir docs\PUBLIC_REPRODUCIBILITY.md. Aucun telechargement automatique.
  goto :failure
)
if not exist "%LOCALASR_PYTHON%" (
  echo Interpreteur configure introuvable.
  goto :failure
)
"%LOCALASR_PYTHON%" -I -B -S "%~dp0launch.py" %*
exit /b %errorlevel%

:failure
if "%~1"=="" pause
exit /b 1
