import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='integrations.tasks.auto_sync_all_git_accounts_task')
def auto_sync_all_git_accounts_task():
    """Celery Beat entry point. Fans out one task per connected account so large
    numbers of accounts sync in parallel across workers, instead of one long
    serial loop blocking a single worker."""
    from integrations.models import GitAccount

    account_ids = list(GitAccount.objects.values_list('id', flat=True))
    for account_id in account_ids:
        auto_sync_account_task.delay(str(account_id))
    return {'dispatched': len(account_ids)}


@shared_task(
    name='integrations.tasks.auto_sync_account_task',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def auto_sync_account_task(self, git_account_id):
    """Auto-syncs a single account — today's commits/merge requests only."""
    from integrations.models import GitAccount
    from integrations.services.sync import auto_sync_account

    try:
        git_account = GitAccount.objects.get(id=git_account_id)
    except GitAccount.DoesNotExist:
        logger.warning('auto_sync_account_task: GitAccount %s no longer exists', git_account_id)
        return

    try:
        auto_sync_account(git_account)
    except Exception as exc:
        logger.exception('Auto sync failed for %s', git_account)
        raise self.retry(exc=exc)
