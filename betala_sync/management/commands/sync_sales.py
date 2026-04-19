"""
Management command for å synkronisere salgsdata fra Betala.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from inventory.models import Event
from betala_sync.services import SyncService
from betala_sync.client import BetalaAPIError


class Command(BaseCommand):
    help = 'Synkroniser salgsdata fra Betala POS og oppdater lagerbeholdning'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--event',
            type=int,
            required=True,
            help='Event ID å synkronisere for'
        )
        parser.add_argument(
            '--from',
            dest='from_date',
            type=str,
            default=None,
            help='Start-dato (YYYY-MM-DD). Default: siste sync eller event-start'
        )
        parser.add_argument(
            '--to',
            dest='to_date',
            type=str,
            default=None,
            help='Slutt-dato (YYYY-MM-DD). Default: i dag'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Synkroniser fra event-startdato (ignorerer siste sync)'
        )
    
    def handle(self, *args, **options):
        # Finn event
        try:
            event = Event.objects.get(pk=options['event'])
        except Event.DoesNotExist:
            raise CommandError(f"Event med ID {options['event']} finnes ikke")
        
        if not event.betala_sales_point_group_id:
            raise CommandError(
                "Event mangler Betala salgspunktgruppe-ID. "
                "Sett dette i Django admin."
            )
        
        # Parse datoer
        start_date = None
        end_date = None
        
        if options['all']:
            start_date = event.start_date
        elif options['from_date']:
            try:
                start_date = date.fromisoformat(options['from_date'])
            except ValueError:
                raise CommandError(f"Ugyldig fra-dato: {options['from_date']}")
        
        if options['to_date']:
            try:
                end_date = date.fromisoformat(options['to_date'])
            except ValueError:
                raise CommandError(f"Ugyldig til-dato: {options['to_date']}")
        
        # Vis info
        if start_date:
            start_info = start_date.isoformat()
        elif event.last_sales_sync:
            start_info = f"siste sync ({event.last_sales_sync.date()})"
        else:
            start_info = f"event-start ({event.start_date})"
        
        end_info = end_date.isoformat() if end_date else "i dag"
        
        self.stdout.write(
            f'Synkroniserer salg for {event.name}\n'
            f'  Sales Point Group: {event.betala_sales_point_group_id}\n'
            f'  Fra: {start_info}\n'
            f'  Til: {end_info}'
        )
        
        try:
            service = SyncService()
            transactions, lines = service.sync_sales(
                event=event,
                start_date=start_date,
                end_date=end_date
            )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSynkronisering fullført!\n'
                    f'  Transaksjoner behandlet: {transactions}\n'
                    f'  Lagerlinjer opprettet: {lines}'
                )
            )
            
        except BetalaAPIError as e:
            raise CommandError(f'API-feil: {e.message}')
        except Exception as e:
            raise CommandError(f'Uventet feil: {e}')
