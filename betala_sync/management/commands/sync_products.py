"""
Management command for å synkronisere produkter fra Betala.
"""

from django.core.management.base import BaseCommand, CommandError

from betala_sync.services import SyncService
from betala_sync.client import BetalaAPIError


class Command(BaseCommand):
    help = 'Synkroniser produkter og kategorier fra Betala POS'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--include-archived',
            action='store_true',
            help='Inkluder arkiverte produkter'
        )
    
    def handle(self, *args, **options):
        self.stdout.write('Starter synkronisering av produkter fra Betala...')
        
        try:
            service = SyncService()
            created, updated, failed = service.sync_products(
                include_archived=options['include_archived']
            )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Synkronisering fullført!\n'
                    f'  Opprettet: {created}\n'
                    f'  Oppdatert: {updated}\n'
                    f'  Feilet: {failed}'
                )
            )
            
        except BetalaAPIError as e:
            raise CommandError(f'API-feil: {e.message}')
        except Exception as e:
            raise CommandError(f'Uventet feil: {e}')
