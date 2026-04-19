# Deployment Guide - Linux med Cloudflare Tunnel

Denne guiden dekker oppsett av lagersystemet på en Linux-server med Cloudflare Tunnel for sikker tilgang.

## Forutsetninger

- Ubuntu 22.04+ / Debian 12+ (eller lignende)
- Python 3.11+
- Cloudflare-konto (gratis)
- Domene pekt til Cloudflare

## 1. Forbered Linux-serveren

```bash
# Oppdater systemet
sudo apt update && sudo apt upgrade -y

# Installer nødvendige pakker
sudo apt install -y python3 python3-pip python3-venv git nginx sqlite3

# Opprett bruker for applikasjonen
sudo useradd -m -s /bin/bash festival
sudo su - festival
```

## 2. Last ned prosjektet

```bash
# Som festival-bruker
cd ~
git clone <your-repo-url> inventory-system
# Eller kopier filene manuelt via SCP/SFTP

cd inventory-system
```

## 3. Sett opp Python-miljø

```bash
# Opprett virtuelt miljø
python3 -m venv venv
source venv/bin/activate

# Installer dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Installer produksjons-webserver
pip install gunicorn
```

## 4. Konfigurer miljøvariabler

```bash
# Kopier og rediger .env
cp .env.example .env
nano .env
```

Rediger `.env` med disse innstillingene:

```env
# Django settings
DJANGO_SECRET_KEY=generer-en-lang-tilfeldig-nøkkel-her
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=ditt-domene.no,localhost

# Database (SQLite for enkelhet, PostgreSQL for produksjon)
USE_SQLITE=true

# Betala API
BETALA_API_BASE_URL=https://api.betala.no
BETALA_ORGANIZATION_ID=din-org-id

# Sikkerhet
CSRF_TRUSTED_ORIGINS=https://ditt-domene.no
```

Generer secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 5. Initialiser databasen

```bash
# Aktiver venv
source venv/bin/activate

# Kjør migrasjoner
python manage.py migrate

# Opprett superbruker (valgfritt)
python manage.py createsuperuser

# Samle statiske filer
python manage.py collectstatic --noinput
```

## 6. Test at det fungerer

```bash
# Kjør utviklingsserver for test
python manage.py runserver 0.0.0.0:8000
# Åpne http://server-ip:8000 i nettleser
# Ctrl+C for å stoppe
```

## 7. Sett opp Gunicorn systemd-service

```bash
# Gå tilbake til root/sudo-bruker
exit

# Kopier service-fil
sudo cp /home/festival/inventory-system/deploy/inventory.service /etc/systemd/system/

# Aktiver og start tjenesten
sudo systemctl daemon-reload
sudo systemctl enable inventory
sudo systemctl start inventory

# Sjekk status
sudo systemctl status inventory
```

## 8. Installer Cloudflare Tunnel (cloudflared)

```bash
# Last ned og installer cloudflared
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Logg inn til Cloudflare (åpner nettleser)
cloudflared tunnel login

# Opprett tunnel
cloudflared tunnel create inventory

# Noter tunnel-ID som vises (f.eks. a1b2c3d4-e5f6-...)
```

## 9. Konfigurer Cloudflare Tunnel

```bash
# Opprett konfigurasjonsfil
sudo mkdir -p /etc/cloudflared
sudo nano /etc/cloudflared/config.yml
```

Legg inn:
```yaml
tunnel: <din-tunnel-id>
credentials-file: /home/festival/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: lager.ditt-domene.no
    service: http://localhost:8000
  - service: http_status:404
```

Kopier credentials:
```bash
sudo cp ~/.cloudflared/<tunnel-id>.json /etc/cloudflared/
sudo chown -R root:root /etc/cloudflared
sudo chmod 600 /etc/cloudflared/*.json
```

## 10. Sett opp DNS i Cloudflare

```bash
# Opprett DNS-record automatisk
cloudflared tunnel route dns inventory lager.ditt-domene.no
```

## 11. Start Cloudflare Tunnel som tjeneste

```bash
# Installer som systemd-tjeneste
sudo cloudflared service install

# Start tjenesten
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

# Sjekk status
sudo systemctl status cloudflared
```

## 12. Verifiser at alt fungerer

1. Åpne `https://lager.ditt-domene.no` i nettleser
2. Du skal se innloggingssiden
3. Logg inn med Betala-brukeren din

## Vedlikehold

### Se logger
```bash
# App-logger
sudo journalctl -u inventory -f

# Cloudflare tunnel logger
sudo journalctl -u cloudflared -f
```

### Oppdater applikasjonen
```bash
sudo su - festival
cd inventory-system
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
exit

sudo systemctl restart inventory
```

### Backup database
```bash
# SQLite backup
cp /home/festival/inventory-system/db.sqlite3 /backup/db-$(date +%Y%m%d).sqlite3
```

## Feilsøking

### App starter ikke
```bash
# Sjekk logger
sudo journalctl -u inventory -n 50

# Test manuelt
sudo su - festival
cd inventory-system
source venv/bin/activate
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

### Cloudflare tunnel fungerer ikke
```bash
# Sjekk tunnel-status
cloudflared tunnel info inventory

# Test lokal tilkobling
curl http://localhost:8000
```

### Statiske filer vises ikke
```bash
# Sjekk at collectstatic er kjørt
ls -la /home/festival/inventory-system/staticfiles/

# I produksjon med DEBUG=False må du serve statiske filer via whitenoise
# Dette er allerede konfigurert i production settings
```

## Sikkerhet

- Cloudflare Tunnel krypterer all trafikk
- Ingen porter eksponert til internett (ingen bruk av 8000, 80, 443)
- Betala-pålogging kreves for tilgang
- Alle sensitive data i .env-fil (ikke i versjonskontroll)

## Oppgradering til PostgreSQL (valgfritt)

For større installasjoner anbefales PostgreSQL:

```bash
# Installer PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Opprett database
sudo -u postgres createuser festival
sudo -u postgres createdb -O festival inventory

# Oppdater .env
USE_SQLITE=false
DATABASE_URL=postgres://festival:passord@localhost/inventory

# Migrer data (eksporter først fra SQLite)
python manage.py dumpdata > data.json
# Bytt til PostgreSQL i .env
python manage.py migrate
python manage.py loaddata data.json
```
