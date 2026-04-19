"""
Views for Betala synkronisering.
"""

from datetime import date, timedelta

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.http import require_POST, require_http_methods
from django.conf import settings

from inventory.models import Event, BetalaSyncLog, Product, Category, AllowedOrganization
from .services import SyncService
from .client import BetalaAPIError, BetalaClientSync, BetalaConfig, authenticate_betala, get_sales_point_areas


# =============================================================================
# BETALA INNLOGGING OG ORGANISASJONSVALG
# =============================================================================

@require_http_methods(["GET", "POST"])
def betala_login(request):
    """Logg inn til Betala og hent organisasjoner."""
    # Hvis allerede innlogget, send til dashboard
    if request.user.is_authenticated and request.session.get('betala_token'):
        return redirect('inventory:dashboard')
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        if not email or not password:
            messages.error(request, 'E-post og passord er påkrevd')
            return render(request, 'betala_sync/login.html')
        
        try:
            # Autentiser mot Betala
            auth_data = authenticate_betala(email, password)
            
            # Finn eller opprett Django-bruker basert på e-post
            user, created = User.objects.get_or_create(
                username=email,
                defaults={
                    'email': email,
                    'first_name': auth_data['user'].get('first_name', ''),
                    'last_name': auth_data['user'].get('last_name', ''),
                }
            )
            
            # Logg inn brukeren i Django
            login(request, user)
            
            # Lagre Betala-data i session
            request.session['betala_token'] = auth_data['token']
            request.session['betala_user'] = auth_data['user']
            request.session['betala_organizations'] = auth_data['organizations']
            
            messages.success(request, f"Logget inn som {auth_data['user'].get('email')}")
            return redirect('betala_sync:select_organization')
            
        except BetalaAPIError as e:
            messages.error(request, f'Innlogging feilet: {e.message}')
        except Exception as e:
            messages.error(request, f'Feil: {e}')
    
    return render(request, 'betala_sync/login.html')


@login_required
def betala_select_organization(request):
    """Velg organisasjon etter innlogging."""
    all_organizations = request.session.get('betala_organizations', [])
    token = request.session.get('betala_token')
    
    if not token or not all_organizations:
        messages.warning(request, 'Du må logge inn på Betala først')
        return redirect('betala_sync:betala_login')
    
    # Hent godkjente organisasjoner fra databasen
    allowed_org_ids = set(
        AllowedOrganization.objects.filter(is_active=True)
        .values_list('betala_org_id', flat=True)
    )
    
    # Filtrer til kun godkjente organisasjoner
    # Sjekker både 'id' og 'organization_id' felt i organisasjonsdata
    organizations = []
    for org in all_organizations:
        org_id = str(org.get('id', '') or org.get('organization_id', ''))
        identifier = str(org.get('identifier', ''))
        
        # Sjekk om organisasjonen er godkjent (via ID eller identifier)
        if org_id in allowed_org_ids or identifier in allowed_org_ids:
            organizations.append(org)
    
    # Debug-logging
    print(f"DEBUG: Antall orgs fra Betala: {len(all_organizations)}")
    print(f"DEBUG: Antall godkjente orgs: {len(allowed_org_ids)}")
    print(f"DEBUG: Antall filtrerte orgs: {len(organizations)}")
    
    if not organizations:
        messages.warning(
            request, 
            'Ingen av dine organisasjoner har tilgang til dette systemet. '
            'Kontakt administrator for å få tilgang.'
        )
    
    context = {
        'organizations': organizations,
        'betala_user': request.session.get('betala_user', {}),
    }
    return render(request, 'betala_sync/select_organization.html', context)


@login_required
@require_POST
def betala_sync_organization(request):
    """Velg organisasjon og gå videre til salgspunkt-område valg."""
    org_id = request.POST.get('organization_id')
    org_name = request.POST.get('organization_name', 'Ukjent')
    
    # Debug logging
    print(f"DEBUG: POST data: {request.POST}")
    print(f"DEBUG: org_id = '{org_id}', org_name = '{org_name}'")
    
    token = request.session.get('betala_token')
    if not token:
        messages.error(request, 'Betala-sesjon utløpt. Logg inn på nytt.')
        return redirect('betala_sync:betala_login')
    
    if not org_id:
        messages.error(request, 'Du må velge en organisasjon')
        return redirect('betala_sync:select_organization')
    
    # Lagre valgt organisasjon i session
    request.session['betala_selected_org_id'] = org_id
    request.session['betala_selected_org_name'] = org_name
    
    # Gå til salgspunkt-område valg
    return redirect('betala_sync:select_sales_point_area')


@login_required
@require_POST
def betala_switch_organization(request):
    """Bytt til en annen organisasjon (fra dropdown i sidebar)."""
    org_id = request.POST.get('organization_id')
    
    token = request.session.get('betala_token')
    organizations = request.session.get('betala_organizations', [])
    
    if not token:
        messages.error(request, 'Betala-sesjon utløpt. Logg inn på nytt.')
        return redirect('betala_sync:betala_login')
    
    if not org_id:
        messages.error(request, 'Du må velge en organisasjon')
        return redirect('inventory:dashboard')
    
    # Finn organisasjonsnavnet
    org_name = 'Ukjent'
    for org in organizations:
        if str(org.get('id')) == str(org_id):
            org_name = org.get('name', 'Ukjent')
            break
    
    # Oppdater valgt organisasjon
    request.session['betala_selected_org_id'] = org_id
    request.session['betala_selected_org_name'] = org_name
    
    # Fjern valgt salgsområde slik at brukeren må velge på nytt
    request.session.pop('betala_selected_area_id', None)
    request.session.pop('betala_selected_area_name', None)
    
    # Gå til salgspunkt-område valg
    return redirect('betala_sync:select_sales_point_area')


@login_required
def betala_select_sales_point_area(request):
    """Velg salgspunkt-område for lageret."""
    token = request.session.get('betala_token')
    org_id = request.session.get('betala_selected_org_id')
    org_name = request.session.get('betala_selected_org_name', 'Ukjent')
    
    if not token or not org_id:
        messages.warning(request, 'Du må velge en organisasjon først')
        return redirect('betala_sync:select_organization')
    
    try:
        # Hent aktive salgspunkt-områder
        active_areas = get_sales_point_areas(token, org_id, is_archived=False)
        # Hent arkiverte salgspunkt-områder
        archived_areas = get_sales_point_areas(token, org_id, is_archived=True)
        
        context = {
            'org_name': org_name,
            'org_id': org_id,
            'active_areas': active_areas,
            'archived_areas': archived_areas,
            'betala_user': request.session.get('betala_user', {}),
        }
        return render(request, 'betala_sync/select_sales_point_area.html', context)
        
    except BetalaAPIError as e:
        messages.error(request, f'Kunne ikke hente salgspunkt-områder: {e.message}')
        return redirect('betala_sync:select_organization')


@login_required
@require_POST
def betala_sync_sales_point_area(request):
    """Synkroniser produkter og transaksjoner for valgt salgspunkt-område."""
    area_id = request.POST.get('sales_point_area_id')
    area_name = request.POST.get('sales_point_area_name', 'Ukjent')
    
    token = request.session.get('betala_token')
    org_id = request.session.get('betala_selected_org_id')
    org_name = request.session.get('betala_selected_org_name', 'Ukjent')
    
    if not token or not org_id:
        messages.error(request, 'Betala-sesjon utløpt. Logg inn på nytt.')
        return redirect('betala_sync:betala_login')
    
    if not area_id:
        messages.error(request, 'Du må velge et salgspunkt-område')
        return redirect('betala_sync:select_sales_point_area')
    
    # Lagre valgt salgspunkt-område i session
    request.session['betala_selected_area_id'] = area_id
    request.session['betala_selected_area_name'] = area_name
    
    try:
        # Opprett eller finn Event for dette salgspunkt-området
        today = date.today()
        event, event_created = Event.objects.update_or_create(
            betala_sales_point_group_id=int(area_id),
            defaults={
                'name': f'{org_name} - {area_name}',
                'start_date': today,
                'end_date': today + timedelta(days=365),  # Standard 1 år
                'location': org_name,
                'betala_organization_id': int(org_id),
                'betala_api_key': token,  # Lagre API-nøkkel for automatisk sync
                'is_active': True,
            }
        )
        
        # Sett som aktivt event i session
        request.session['active_event_id'] = event.id
        
        # Opprett klient med token og valgt org
        config = BetalaConfig(
            base_url=settings.BETALA_API_URL,
            api_key=token,
            organization_id=org_id,
        )
        
        products_synced = 0
        products_updated = 0
        products_matched = 0  # Produkter matchet via ID-endring
        transactions_synced = 0
        
        with BetalaClientSync(config=config) as client:
            # Hent produkter fra Betala
            betala_products = client.get_products(org_id=int(org_id))
            
            # Samle alle produkt-IDer fra Betala
            betala_product_ids = {p.get('product_id') for p in betala_products}
            
            # Hent alle eksisterende produkter for denne organisasjonen
            existing_products = {
                p.betala_product_id: p 
                for p in Product.objects.filter(betala_organization_id=int(org_id))
            }
            existing_by_name = {
                p.name: p 
                for p in Product.objects.filter(betala_organization_id=int(org_id))
            }
            
            # Finn produkter som "mangler" i Betala (ID ikke lenger gyldig)
            orphaned_products = []
            for old_id, product in existing_products.items():
                if old_id and old_id not in betala_product_ids:
                    orphaned_products.append(product)
            
            # Produkter fra Betala som ikke matcher på ID eller navn
            unmatched_betala_products = []
            
            # Første pass: Match på ID eller navn
            for prod_data in betala_products:
                betala_product_id = prod_data.get('product_id')
                product_name = prod_data.get('name', 'Ukjent')
                
                # Prøv å finne på gjeldende ID først
                existing_product = existing_products.get(betala_product_id)
                
                # Hvis ikke funnet på ID, prøv på navn
                if not existing_product:
                    existing_product = existing_by_name.get(product_name)
                
                if existing_product:
                    # Sjekk om ID har endret seg
                    old_id = existing_product.betala_product_id
                    if old_id and old_id != betala_product_id:
                        # Legg gammel ID i previous_ids
                        if existing_product.betala_previous_ids is None:
                            existing_product.betala_previous_ids = []
                        if old_id not in existing_product.betala_previous_ids:
                            existing_product.betala_previous_ids.append(old_id)
                    
                    # Oppdater produktet
                    existing_product.betala_product_id = betala_product_id
                    existing_product.name = product_name
                    existing_product.description = prod_data.get('description', '')
                    existing_product.category_name = prod_data.get('category', '')
                    existing_product.price_ore = prod_data.get('price')
                    existing_product.vat_ore = prod_data.get('vat')
                    existing_product.vat_factor = prod_data.get('vat_factor', 2500)
                    existing_product.is_active = not prod_data.get('is_archived', False)
                    existing_product.betala_article_group_id = prod_data.get('article_group_id', '')
                    existing_product.betala_tag = prod_data.get('tag', 0)
                    existing_product.betala_open_price = prod_data.get('open_price', False)
                    existing_product.betala_is_bundles = prod_data.get('is_bundles', False)
                    existing_product.betala_is_bar_printing = prod_data.get('is_bar_printing', False)
                    existing_product.betala_is_kitchen_printing = prod_data.get('is_kitchen_printing', False)
                    existing_product.betala_general_ledger_account = prod_data.get('general_ledger_account')
                    existing_product.save()
                    products_updated += 1
                    
                    # Fjern fra orphaned-listen hvis den var der
                    if existing_product in orphaned_products:
                        orphaned_products.remove(existing_product)
                else:
                    # Ikke matchet - legg til for andre pass
                    unmatched_betala_products.append(prod_data)
            
            # Andre pass: Match orphaned produkter med nye basert på likheter
            # Dette håndterer tilfeller der både ID OG navn har endret seg
            for prod_data in unmatched_betala_products[:]:  # Kopier listen for å kunne mutere
                betala_product_id = prod_data.get('product_id')
                product_name = prod_data.get('name', 'Ukjent')
                category = prod_data.get('category', '')
                article_group = prod_data.get('article_group_id', '')
                
                best_match = None
                best_score = 0
                
                for orphan in orphaned_products:
                    score = 0
                    
                    # Samme kategori gir poeng
                    if orphan.category_name and orphan.category_name == category:
                        score += 3
                    
                    # Samme artikkelgruppe gir poeng
                    if orphan.betala_article_group_id and orphan.betala_article_group_id == article_group:
                        score += 2
                    
                    # Lignende navn (inneholder samme ord)
                    orphan_words = set(orphan.name.lower().split())
                    new_words = set(product_name.lower().split())
                    common_words = orphan_words & new_words
                    if common_words:
                        score += len(common_words) * 2
                    
                    if score > best_score:
                        best_score = score
                        best_match = orphan
                
                # Krev minimum score for å matche (unngå feil-match)
                # ELLER hvis det bare er én orphan og én unmatched
                if best_match and (best_score >= 3 or (len(orphaned_products) == 1 and len(unmatched_betala_products) == 1)):
                    # Match funnet - oppdater orphan med ny data
                    old_id = best_match.betala_product_id
                    
                    # Legg gammel ID i previous_ids
                    if best_match.betala_previous_ids is None:
                        best_match.betala_previous_ids = []
                    if old_id and old_id not in best_match.betala_previous_ids:
                        best_match.betala_previous_ids.append(old_id)
                    
                    best_match.betala_product_id = betala_product_id
                    best_match.name = product_name
                    best_match.description = prod_data.get('description', '')
                    best_match.category_name = category
                    best_match.price_ore = prod_data.get('price')
                    best_match.vat_ore = prod_data.get('vat')
                    best_match.vat_factor = prod_data.get('vat_factor', 2500)
                    best_match.is_active = not prod_data.get('is_archived', False)
                    best_match.betala_article_group_id = article_group
                    best_match.betala_tag = prod_data.get('tag', 0)
                    best_match.betala_open_price = prod_data.get('open_price', False)
                    best_match.betala_is_bundles = prod_data.get('is_bundles', False)
                    best_match.betala_is_bar_printing = prod_data.get('is_bar_printing', False)
                    best_match.betala_is_kitchen_printing = prod_data.get('is_kitchen_printing', False)
                    best_match.betala_general_ledger_account = prod_data.get('general_ledger_account')
                    best_match.save()
                    
                    orphaned_products.remove(best_match)
                    unmatched_betala_products.remove(prod_data)
                    products_matched += 1
            
            # Opprett nye produkter for de som fortsatt er unmatched
            for prod_data in unmatched_betala_products:
                Product.objects.create(
                    betala_organization_id=int(org_id),
                    betala_product_id=prod_data.get('product_id'),
                    name=prod_data.get('name', 'Ukjent'),
                    description=prod_data.get('description', ''),
                    category_name=prod_data.get('category', ''),
                    price_ore=prod_data.get('price'),
                    vat_ore=prod_data.get('vat'),
                    vat_factor=prod_data.get('vat_factor', 2500),
                    is_active=not prod_data.get('is_archived', False),
                    betala_article_group_id=prod_data.get('article_group_id', ''),
                    betala_tag=prod_data.get('tag', 0),
                    betala_open_price=prod_data.get('open_price', False),
                    betala_is_bundles=prod_data.get('is_bundles', False),
                    betala_is_bar_printing=prod_data.get('is_bar_printing', False),
                    betala_is_kitchen_printing=prod_data.get('is_kitchen_printing', False),
                    betala_general_ledger_account=prod_data.get('general_ledger_account'),
                )
                products_synced += 1
            
            # Orphaned produkter som ikke ble matchet - disse er ekte slettede/arkiverte
            # IKKE deaktiver - behold for lagerhistorikk, men logg
            if orphaned_products:
                orphan_names = ', '.join([p.name for p in orphaned_products[:5]])
                if len(orphaned_products) > 5:
                    orphan_names += f' (+{len(orphaned_products) - 5} til)'
                messages.info(
                    request,
                    f'OBS: {len(orphaned_products)} produkt(er) finnes ikke lenger i Betala: {orphan_names}. '
                    f'Disse beholdes for lagerhistorikk.'
                )
            
            # Hent transaksjoner for valgt salgspunktgruppe
            try:
                transactions = client.get_transactions(
                    sales_point_group_id=int(area_id),
                    org_id=int(org_id),
                    limit=1200
                )
                transactions_synced = len(transactions)
            except Exception as e:
                # Transaksjoner kan mangle
                pass
        
        action = 'opprettet' if event_created else 'oppdatert'
        
        # Bygg opp melding med detaljer
        product_msg_parts = []
        if products_synced > 0:
            product_msg_parts.append(f'{products_synced} nye')
        if products_updated > 0:
            product_msg_parts.append(f'{products_updated} oppdatert')
        if products_matched > 0:
            product_msg_parts.append(f'{products_matched} matchet (ID-endring)')
        product_msg = ', '.join(product_msg_parts) if product_msg_parts else '0'
        
        messages.success(
            request,
            f'Event "{event.name}" {action}. '
            f'Produkter: {product_msg}. Transaksjoner: {transactions_synced}'
        )
        
        # Gå rett til dashboard
        return redirect('inventory:dashboard')
        
    except BetalaAPIError as e:
        messages.error(request, f'API-feil: {e.message}')
    except Exception as e:
        messages.error(request, f'Feil ved synkronisering: {e}')
    
    return redirect('betala_sync:select_sales_point_area')


@login_required
def betala_sync_result(request):
    """Vis resultat av synkronisering."""
    context = {
        'org_name': request.session.get('betala_selected_org_name', 'Ukjent'),
        'org_id': request.session.get('betala_selected_org_id'),
        'transactions': request.session.get('betala_transactions', []),
        'transactions_total': request.session.get('betala_transactions_total', 0),
        'products': Product.objects.filter(betala_product_id__isnull=False).order_by('-updated_at')[:50],
    }
    return render(request, 'betala_sync/sync_result.html', context)


def betala_logout(request):
    """Logg ut fra både Django og Betala."""
    # Fjern Betala session-data
    keys_to_remove = [
        'betala_token', 'betala_user', 'betala_organizations',
        'betala_selected_org_id', 'betala_selected_org_name',
        'betala_selected_area_id', 'betala_selected_area_name',
        'betala_transactions', 'betala_transactions_total'
    ]
    for key in keys_to_remove:
        request.session.pop(key, None)
    
    # Logg ut fra Django
    logout(request)
    
    messages.info(request, 'Du er nå logget ut')
    return redirect('betala_sync:betala_login')


# =============================================================================
# EKSISTERENDE VIEWS
# =============================================================================


@login_required
def sync_dashboard(request):
    """Oversikt over synkroniseringsstatus."""
    recent_logs = BetalaSyncLog.objects.all()[:10]
    events = Event.objects.filter(
        is_active=True,
        betala_sales_point_group_id__isnull=False
    )
    
    context = {
        'recent_logs': recent_logs,
        'events': events,
    }
    return render(request, 'betala_sync/dashboard.html', context)


@login_required
@require_POST
def sync_products(request):
    """Kjør produktsynkronisering."""
    try:
        service = SyncService(user=request.user)
        created, updated, failed = service.sync_products()
        
        messages.success(
            request,
            f'Synkronisering fullført! Opprettet: {created}, '
            f'Oppdatert: {updated}, Feilet: {failed}'
        )
    except BetalaAPIError as e:
        messages.error(request, f'API-feil: {e.message}')
    except Exception as e:
        messages.error(request, f'Feil: {e}')
    
    return redirect('betala_sync:dashboard')


@login_required
@require_POST
def sync_sales(request):
    """Kjør salgssynkronisering for et event."""
    event_id = request.POST.get('event_id')
    from_date = request.POST.get('from_date')
    to_date = request.POST.get('to_date')
    sync_all = request.POST.get('sync_all') == 'true'
    
    # Hent event - bruk aktiv event fra session hvis ikke oppgitt
    if not event_id:
        event_id = request.session.get('active_event_id')
    
    if not event_id:
        messages.error(request, 'Du må velge et event')
        return redirect('inventory:dashboard')
    
    try:
        event = Event.objects.get(pk=event_id)
    except Event.DoesNotExist:
        messages.error(request, 'Event ikke funnet')
        return redirect('inventory:dashboard')
    
    if not event.betala_sales_point_group_id:
        messages.error(request, 'Event mangler Betala salgspunktgruppe')
        return redirect('inventory:dashboard')
    
    # Parse datoer
    start_date = None
    end_date = None
    
    if sync_all:
        start_date = event.start_date
    elif from_date:
        try:
            start_date = date.fromisoformat(from_date)
        except ValueError:
            messages.error(request, f'Ugyldig fra-dato: {from_date}')
            return redirect('inventory:dashboard')
    
    if to_date:
        try:
            end_date = date.fromisoformat(to_date)
        except ValueError:
            messages.error(request, f'Ugyldig til-dato: {to_date}')
            return redirect('inventory:dashboard')
    
    try:
        service = SyncService(user=request.user)
        transactions, lines = service.sync_sales(
            event=event,
            start_date=start_date,
            end_date=end_date
        )
        
        if transactions > 0:
            messages.success(
                request,
                f'Salgssynkronisering fullført! '
                f'{transactions} transaksjoner, {lines} lagerlinjer oppdatert'
            )
        else:
            messages.info(
                request,
                'Ingen nye transaksjoner å synkronisere'
            )
    except BetalaAPIError as e:
        messages.error(request, f'API-feil: {e.message}')
    except ValueError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, f'Feil ved synkronisering: {e}')
    
    # Gå tilbake dit brukeren kom fra
    next_url = request.POST.get('next', 'inventory:dashboard')
    return redirect(next_url)


@login_required
def sync_log_list(request):
    """Liste over synkroniseringslogger."""
    logs = BetalaSyncLog.objects.all()[:50]
    
    context = {
        'logs': logs,
    }
    return render(request, 'betala_sync/log_list.html', context)
