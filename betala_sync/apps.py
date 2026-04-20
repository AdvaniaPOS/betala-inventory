from django.apps import AppConfig


class BetalaSyncConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'betala_sync'
    verbose_name = 'Betala Synkronisering'
    
    def ready(self):
        """Start scheduler når Django er klar."""
        from django.conf import settings
        import os
        import sys
        
        # Ikke start scheduler under management-kommandoer (migrate, shell, etc.)
        is_management_command = len(sys.argv) > 1 and sys.argv[1] in [
            'migrate', 'makemigrations', 'shell', 'dbshell', 'createsuperuser',
            'collectstatic', 'check', 'test', 'flush', 'showmigrations'
        ]
        
        if is_management_command:
            return
        
        # Bare start scheduler i hovedprosessen (ikke i manage.py kommandoer)
        # og bare i runserver, ikke i migrate, shell etc.
        if os.environ.get('RUN_MAIN') == 'true' or not settings.DEBUG:
            from betala_sync import jobs
            jobs.start_scheduler()
