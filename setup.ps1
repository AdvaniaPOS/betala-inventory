# Betala Inventory - Oppsett
# Kjør dette skriptet for å sette opp utviklingsmiljø

Write-Host "=== Betala Inventory Oppsett ===" -ForegroundColor Cyan

# Sjekk at vi er i riktig mappe
if (-not (Test-Path "manage.py")) {
    Write-Host "Feil: Kjør skriptet fra inventory-system mappen" -ForegroundColor Red
    exit 1
}

# Opprett virtuelt miljø
if (-not (Test-Path "venv")) {
    Write-Host "Oppretter virtuelt miljø..." -ForegroundColor Yellow
    python -m venv venv
}

# Aktiver virtuelt miljø
Write-Host "Aktiverer virtuelt miljø..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

# Installer avhengigheter
Write-Host "Installerer Python-pakker..." -ForegroundColor Yellow
pip install -r requirements.txt

# Kopier .env hvis den ikke finnes
if (-not (Test-Path ".env")) {
    Write-Host "Oppretter .env fra eksempel..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    
    # Generer SECRET_KEY
    $secretKey = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 50 | ForEach-Object {[char]$_})
    (Get-Content ".env") -replace "generer-en-ny-sikker-nøkkel-her", $secretKey | Set-Content ".env"
    
    Write-Host "OBS: Rediger .env med riktige verdier for database og Betala API" -ForegroundColor Yellow
}

# Opprett nødvendige mapper
$folders = @("static", "media", "staticfiles")
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder | Out-Null
    }
}

Write-Host ""
Write-Host "=== Oppsett fullført! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Neste steg:"
Write-Host "1. Rediger .env med database-innstillinger"
Write-Host "2. Opprett PostgreSQL database:"
Write-Host "   CREATE DATABASE festival_inventory;"
Write-Host "3. Kjør migrasjoner:"
Write-Host "   python manage.py migrate"
Write-Host "4. Opprett admin-bruker:"
Write-Host "   python manage.py createsuperuser"
Write-Host "5. Start utviklingsserver:"
Write-Host "   python manage.py runserver"
Write-Host ""
