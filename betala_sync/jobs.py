"""
Scheduled jobs for Betala sync.

Kjører automatisk synkronisering av salg fra Betala hvert 15. minutt.
"""

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from django.utils import timezone
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None


def sync_all_events_sales():
    """
    Synkroniser salg for alle aktive events.
    Kjører automatisk hvert 15. minutt.
    """
    from inventory.models import Event
    from betala_sync.services import SyncService
    
    logger.info("Starter automatisk salgssynkronisering...")
    
    # Kun events med auto_sync_enabled=True
    sync_events = Event.objects.filter(is_active=True, auto_sync_enabled=True)
    
    if not sync_events.exists():
        logger.info("Ingen events med automatisk synkronisering aktivert")
        return
    
    for event in sync_events:
        if not event.betala_sales_point_group_id:
            logger.warning(f"Event '{event.name}' mangler Betala sales_point_group_id")
            continue
        
        try:
            api_key = event.betala_api_key
            if not api_key:
                logger.warning(f"Event '{event.name}' mangler API-nøkkel for automatisk sync")
                continue
            
            # Opprett klient med riktig API-nøkkel for dette eventet
            from betala_sync.client import BetalaClientSync, BetalaConfig
            from django.conf import settings
            
            config = BetalaConfig(
                base_url=settings.BETALA_API_URL,
                api_key=api_key,
                organization_id=str(event.betala_organization_id),
            )
            
            service = SyncService()
            service.client = BetalaClientSync(config=config)
            
            # Synk siste 24 timer, eller fra siste sync
            if event.last_sales_sync:
                from_date = event.last_sales_sync.date()
            else:
                from_date = (timezone.now() - timedelta(days=1)).date()
            
            to_date = timezone.now().date()
            
            transactions_synced, lines_synced = service.sync_sales(
                event=event,
                start_date=from_date,
                end_date=to_date
            )
            
            logger.info(
                f"Synkroniserte event '{event.name}': "
                f"{transactions_synced} transaksjoner, "
                f"{lines_synced} lagerlinjer"
            )
            
        except Exception as e:
            logger.error(f"Feil ved synkronisering av event '{event.name}': {e}")
    
    logger.info("Automatisk salgssynkronisering fullført")


def delete_old_job_executions(max_age=604_800):
    """
    Slett gamle job executions som er eldre enn max_age sekunder (standard 7 dager).
    """
    DjangoJobExecution.objects.delete_old_job_executions(max_age)


def start_scheduler():
    """
    Start APScheduler i bakgrunnen.
    """
    global scheduler
    
    if scheduler is not None and scheduler.running:
        logger.info("Scheduler kjører allerede")
        return
    
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), "default")
    
    # Legg til synkroniseringsjobb - kjører hvert 15. minutt på faste tidspunkt
    # :00, :15, :30, :45 hver time
    scheduler.add_job(
        sync_all_events_sales,
        trigger=CronTrigger(minute='0,15,30,45'),
        id="sync_sales_job",
        name="Synkroniser salg fra Betala",
        replace_existing=True,
        max_instances=1,
    )
    
    # Legg til opprydningsjobb - kjører hver dag
    scheduler.add_job(
        delete_old_job_executions,
        trigger=IntervalTrigger(days=1),
        id="delete_old_job_executions",
        name="Slett gamle job-kjøringer",
        replace_existing=True,
        max_instances=1,
    )
    
    logger.info("Starter APScheduler...")
    scheduler.start()
    logger.info("APScheduler startet - salgssynkronisering kjører hvert 15. minutt")


def stop_scheduler():
    """
    Stopp scheduler.
    """
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler stoppet")
