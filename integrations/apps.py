from django.apps import AppConfig
import threading
from django.test import Client
from django.utils import timezone
import sys
import time
class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations'

    def ready(self):
        skip_commands = {
            "migrate",
            "makemigrations",
            "collectstatic",
            "shell",
            "dbshell",
            "test",
            "createsuperuser",
        }
        if any(cmd in sys.argv for cmd in skip_commands):
            return


        if not hasattr(self, 'scheduler_thread'):
            self.scheduler_thread = threading.Thread(target=self.schedule_task, daemon=True)
            self.scheduler_thread.start()


    def schedule_task(self):
        client = Client()

        last_sync_run = None

        while True:
            try:
                now = timezone.localtime()

                current_date = now.date()

                if (
                    now.hour == 18 and
                    now.minute == 1 and
                    last_sync_run != current_date
                ):
                    response = client.get('/api/integrations/auto-sync/')

                    last_sync_run = current_date

                time.sleep(60)
            except Exception as e:
                pass