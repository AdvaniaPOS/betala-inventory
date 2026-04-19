# Betala Inventory

Komplett lagerstyringssystem med integrasjon mot Betala POS.

## Funksjoner

- 📦 **Varemottak** - Registrer innkommende varer med leverandør og batch-tracking
- 📊 **Sanntids lagerstatus** - Oversikt over alle produkter og beholdning
- 🗑️ **Svinn-registrering** - Registrer svinn, kasse, prøvesmaking etc.
- 🔄 **Betala-synkronisering** - Automatisk import av produkter og salgsdata
- 📈 **Rapporter** - Daglige, ukentlige og event-baserte rapporter
- 📱 **Mobiloptimalisert** - Fungerer på nettbrett og mobil

## Oppsett

### 1. Opprett virtuelt miljø

```powershell
cd inventory-system
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Konfigurer miljøvariabler

Kopier `.env.example` til `.env` og fyll inn verdier:

```powershell
copy .env.example .env
```

### 3. Opprett database

Opprett en PostgreSQL database:

```sql
CREATE DATABASE festival_inventory;
CREATE USER inventory_user WITH PASSWORD 'ditt_passord';
GRANT ALL PRIVILEGES ON DATABASE festival_inventory TO inventory_user;
```

### 4. Kjør migrasjoner

```powershell
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start utviklingsserver

```powershell
python manage.py runserver
```

Nå er systemet tilgjengelig på `http://localhost:8000`

## Betala-integrasjon

For å koble til Betala POS, må du:

1. Skaffe API-nøkkel fra Betala
2. Legge til URL og nøkkel i `.env`
3. Kjøre innledende synkronisering:

```powershell
python manage.py sync_products
python manage.py sync_sales --date today
```

## Prosjektstruktur

```
inventory-system/
├── config/                 # Django prosjektkonfigurasjon
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── inventory/              # Hoved lager-app
│   ├── models.py           # Databasemodeller
│   ├── views.py            # Views og forms
│   ├── admin.py            # Django admin
│   ├── api/                # REST API
│   └── templates/          # HTML templates
├── betala_sync/            # Betala integrasjon
│   ├── client.py           # API klient
│   └── tasks.py            # Celery tasks
├── reports/                # Rapport-app
│   ├── generators.py       # Rapportgenerering
│   └── views.py
└── manage.py
```

## Deployment på lokal server

For festival/event deployment:

1. Installer på lokal server med PostgreSQL
2. Konfigurer med stabil strøm og nettverkstilgang
3. Sett opp automatisk backup
4. Vurder Redis + Celery for bakgrunnssynking

## Lisens

Privat - Kun for intern bruk
