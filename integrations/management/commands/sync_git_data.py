from django.core.management.base import BaseCommand

from integrations.models import GitAccount
from integrations.services.sync import auto_sync_account, sync_account


class Command(BaseCommand):
    help = (
        'Sync repositories, commits, and merge requests for all connected GitHub/GitLab '
        'accounts. By default does a full history sync; pass --auto to only pull today\'s '
        'data, the same as the scheduled Celery task.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider',
            choices=[GitAccount.Provider.GITHUB, GitAccount.Provider.GITLAB],
            help='Only sync accounts for this provider.',
        )
        parser.add_argument(
            '--auto',
            action='store_true',
            help="Today's data only, matching the scheduled Celery auto-sync.",
        )

    def handle(self, *args, **options):
        accounts = GitAccount.objects.all()
        if options['provider']:
            accounts = accounts.filter(provider=options['provider'])

        sync_fn = auto_sync_account if options['auto'] else sync_account

        for git_account in accounts:
            self.stdout.write(f'Syncing {git_account}...')
            try:
                sync_fn(git_account)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f'  failed: {exc}')
            else:
                self.stdout.write(self.style.SUCCESS('  done'))
