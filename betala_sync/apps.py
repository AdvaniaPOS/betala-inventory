from django.apps import AppConfig


class BetalaSyncConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'betala_sync'
    verbose_name = 'Betala Synkronisering'
    
    def ready(self):
        """Start scheduler når Django er klar."""
        from django.conf import settings
        import os
        
        # Bare start scheduler i hovedprosessen (ikke i manage.py kommandoer)
        # og bare i runserver, ikke i migrate, shell etc.
        if os.environ.get('RUN_MAIN') == 'true' or not settings.DEBUG:
            from betala_sync import jobs
            jobs.start_scheduler()
