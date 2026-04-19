#!/bin/bash
# Setup-skript for Betala Inventory på Linux
# Kjør: chmod +x setup.sh && ./setup.sh

set -e

echo "=========================================="
echo "Betala Inventory - Linux Setup"
echo "=========================================="

# Sjekk Python versjon
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "Python versjon: $PYTHON_VERSION"

# Opprett virtuelt miljø
if [ ! -d "venv" ]; then
    echo "Oppretter virtuelt miljø..."
    python3 -m venv venv
fi

# Aktiver venv
source venv/bin/activate

# Oppgrader pip
echo "Oppgraderer pip..."
pip install --upgrade pip

# Installer dependencies
echo "Installerer avhengigheter..."
pip install -r requirements.txt

# Opprett logs mappe
mkdir -p logs

# Kopier .env hvis den ikke finnes
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "Kopierer .env.example til .env..."
        cp .env.example .env
        echo ""
        echo "VIKTIG: Rediger .env med dine innstillinger!"
        echo "  nano .env"
        echo ""
    fi
fi

# Kjør migrasjoner
echo "Kjører database-migrasjoner..."
python manage.py migrate

# Samle statiske filer
echo "Samler statiske filer..."
python manage.py collectstatic --noinput

echo ""
echo "=========================================="
echo "Setup fullført!"
echo "=========================================="
echo ""
echo "Neste steg:"
echo "1. Rediger .env med dine innstillinger"
echo "2. Test: python manage.py runserver 0.0.0.0:8000"
echo "3. For produksjon: Se DEPLOY.md"
echo ""
