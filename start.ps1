$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ est nécessaire pour créer cet environnement.' }
}

& .\.venv\Scripts\python.exe -c 'import importlib.util, sys; sys.exit(not all(importlib.util.find_spec(name) for name in ("flask", "openai", "dotenv", "pypdf", "docx", "waitress", "tzdata")))'
if ($LASTEXITCODE -ne 0) {
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "L'installation des dépendances a échoué." }
}

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Ajoutez votre GROQ_API_KEY dans .env pour activer les réponses IA.'
}

& .\.venv\Scripts\python.exe run.py
