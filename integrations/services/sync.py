import logging
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone

from integrations.models import Commit, CommitFile, GitAccount, MergeRequest, Repository
from integrations.services import github, gitlab

logger = logging.getLogger(__name__)


def _parse_iso(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(dt_timezone.utc)


def _start_of_today():
    """UTC midnight — the cutoff auto-sync uses so it only pulls what's new today,
    instead of re-fetching commits/merge requests from earlier days that are already synced."""
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


# --------------------------------------------------------------------------
# Shared upsert helpers — used by both manual (full) and auto (today-only) sync
# --------------------------------------------------------------------------

def _upsert_repository_from_github(git_account, repo_data):
    repository, _ = Repository.objects.update_or_create(
        git_account=git_account,
        provider_repo_id=str(repo_data['id']),
        defaults={
            'name': repo_data['name'],
            'full_name': repo_data['full_name'],
            'description': repo_data.get('description') or '',
            'url': repo_data['html_url'],
            'default_branch': repo_data.get('default_branch', ''),
            'is_private': repo_data.get('private', False),
            'last_synced_at': timezone.now(),
        },
    )
    return repository


def _upsert_repository_from_gitlab(git_account, repo_data):
    repository, _ = Repository.objects.update_or_create(
        git_account=git_account,
        provider_repo_id=str(repo_data['id']),
        defaults={
            'name': repo_data['name'],
            'full_name': repo_data['path_with_namespace'],
            'description': repo_data.get('description') or '',
            'url': repo_data['web_url'],
            'default_branch': repo_data.get('default_branch') or '',
            'is_private': repo_data.get('visibility') != 'public',
            'last_synced_at': timezone.now(),
        },
    )
    return repository


def _upsert_github_commit(repository, commit_data):
    commit_info = commit_data.get('commit', {})
    author = commit_info.get('author', {}) or {}
    return Commit.objects.update_or_create(
        repository=repository,
        sha=commit_data['sha'],
        defaults={
            'message': commit_info.get('message', ''),
            'author_name': author.get('name', ''),
            'author_email': author.get('email', ''),
            'authored_at': _parse_iso(author.get('date')),
            'url': commit_data.get('html_url', ''),
        },
    )


def _upsert_gitlab_commit(repository, commit_data):
    stats = commit_data.get('stats') or {}
    return Commit.objects.update_or_create(
        repository=repository,
        sha=commit_data['id'],
        defaults={
            'message': commit_data.get('message', ''),
            'author_name': commit_data.get('author_name', ''),
            'author_email': commit_data.get('author_email', ''),
            'authored_at': _parse_iso(commit_data.get('authored_date')),
            'url': commit_data.get('web_url', ''),
            'additions': stats.get('additions'),
            'deletions': stats.get('deletions'),
        },
    )


def _sync_github_commit_files(git_account, commit, owner, name, sha):
    detail = github.get_commit_detail(git_account.access_token, owner, name, sha)
    for file_data in detail.get('files', []):
        CommitFile.objects.update_or_create(
            commit=commit,
            filename=file_data['filename'],
            defaults={
                'status': file_data.get('status', ''),
                'additions': file_data.get('additions'),
                'deletions': file_data.get('deletions'),
                'patch': file_data.get('patch', ''),
            },
        )


def _sync_gitlab_commit_files(git_account, commit, project_id, sha):
    for diff in gitlab.get_commit_diff(git_account.access_token, project_id, sha):
        filename = diff.get('new_path') or diff.get('old_path')
        if diff.get('new_file'):
            change_status = CommitFile.ChangeType.ADDED
        elif diff.get('deleted_file'):
            change_status = CommitFile.ChangeType.REMOVED
        elif diff.get('renamed_file'):
            change_status = CommitFile.ChangeType.RENAMED
        else:
            change_status = CommitFile.ChangeType.MODIFIED

        CommitFile.objects.update_or_create(
            commit=commit,
            filename=filename,
            defaults={'status': change_status, 'patch': diff.get('diff', '')},
        )


def _github_pr_provider_state(pr_data):
    if pr_data.get('merged_at'):
        return MergeRequest.ProviderState.MERGED
    if pr_data.get('state') == 'closed':
        return MergeRequest.ProviderState.CLOSED
    return MergeRequest.ProviderState.OPEN


def _upsert_github_merge_request(repository, pr_data):
    head = pr_data.get('head') or {}
    base = pr_data.get('base') or {}
    MergeRequest.objects.update_or_create(
        repository=repository,
        provider_mr_id=str(pr_data['number']),
        defaults={
            'title': pr_data.get('title', ''),
            'description': pr_data.get('body') or '',
            'author_name': (pr_data.get('user') or {}).get('login', ''),
            'source_branch': head.get('ref', ''),
            'target_branch': base.get('ref', ''),
            'url': pr_data.get('html_url', ''),
            'provider_state': _github_pr_provider_state(pr_data),
            'provider_created_at': _parse_iso(pr_data.get('created_at')),
            'provider_updated_at': _parse_iso(pr_data.get('updated_at')),
        },
    )


_GITLAB_MR_STATE_MAP = {
    'opened': MergeRequest.ProviderState.OPEN,
    'locked': MergeRequest.ProviderState.OPEN,
    'closed': MergeRequest.ProviderState.CLOSED,
    'merged': MergeRequest.ProviderState.MERGED,
}


def _upsert_gitlab_merge_request(repository, mr_data):
    MergeRequest.objects.update_or_create(
        repository=repository,
        provider_mr_id=str(mr_data['iid']),
        defaults={
            'title': mr_data.get('title', ''),
            'description': mr_data.get('description') or '',
            'author_name': (mr_data.get('author') or {}).get('username', ''),
            'source_branch': mr_data.get('source_branch', ''),
            'target_branch': mr_data.get('target_branch', ''),
            'url': mr_data.get('web_url', ''),
            'provider_state': _GITLAB_MR_STATE_MAP.get(
                mr_data.get('state'), MergeRequest.ProviderState.OPEN
            ),
            'provider_created_at': _parse_iso(mr_data.get('created_at')),
            'provider_updated_at': _parse_iso(mr_data.get('updated_at')),
        },
    )


# --------------------------------------------------------------------------
# MANUAL sync — full history, triggered on demand (SyncView / sync_git_data command)
# --------------------------------------------------------------------------

def sync_github_account(git_account):
    token = git_account.access_token

    for repo_data in github.iter_repositories(token):
        repository = _upsert_repository_from_github(git_account, repo_data)
        owner, name = repo_data['full_name'].split('/', 1)

        for commit_data in github.iter_commits(token, owner, name):
            commit, created = _upsert_github_commit(repository, commit_data)
            if created or not commit.files.exists():
                _sync_github_commit_files(git_account, commit, owner, name, commit_data['sha'])

        for pr_data in github.iter_pull_requests(token, owner, name):
            _upsert_github_merge_request(repository, pr_data)

    git_account.last_synced_at = timezone.now()
    git_account.save(update_fields=['last_synced_at'])


def sync_gitlab_account(git_account):
    token = git_account.access_token

    for repo_data in gitlab.iter_repositories(token):
        repository = _upsert_repository_from_gitlab(git_account, repo_data)

        for commit_data in gitlab.iter_commits(token, repo_data['id']):
            commit, created = _upsert_gitlab_commit(repository, commit_data)
            if created or not commit.files.exists():
                _sync_gitlab_commit_files(git_account, commit, repo_data['id'], commit_data['id'])

        for mr_data in gitlab.iter_merge_requests(token, repo_data['id']):
            _upsert_gitlab_merge_request(repository, mr_data)

    git_account.last_synced_at = timezone.now()
    git_account.save(update_fields=['last_synced_at'])


def sync_account(git_account):
    if git_account.provider == GitAccount.Provider.GITHUB:
        sync_github_account(git_account)
    elif git_account.provider == GitAccount.Provider.GITLAB:
        sync_gitlab_account(git_account)
    else:
        raise ValueError(f'Unknown provider: {git_account.provider}')


def sync_all_accounts_for_user(user):
    """Manual, full sync — e.g. a user clicking "Sync now" in the UI."""
    results = []
    for git_account in user.git_accounts.all():
        sync_account(git_account)
        results.append(git_account)
    return results


# --------------------------------------------------------------------------
# AUTO sync — today's data only, run on a schedule via Celery (see integrations/tasks.py)
# --------------------------------------------------------------------------

def auto_sync_github_account(git_account):
    token = git_account.access_token
    since = _start_of_today()
    since_iso = since.isoformat()

    for repo_data in github.iter_repositories(token):
        repository = _upsert_repository_from_github(git_account, repo_data)
        owner, name = repo_data['full_name'].split('/', 1)

        for commit_data in github.iter_commits(token, owner, name, since=since_iso):
            commit, created = _upsert_github_commit(repository, commit_data)
            if created or not commit.files.exists():
                _sync_github_commit_files(git_account, commit, owner, name, commit_data['sha'])

        # No date filter on GitHub's PR list endpoint, so page newest-updated-first
        # and stop as soon as we reach a PR that hasn't changed today.
        for pr_data in github.iter_pull_requests(token, owner, name, sort='updated', direction='desc'):
            updated_at = _parse_iso(pr_data.get('updated_at'))
            if updated_at and updated_at < since:
                break
            _upsert_github_merge_request(repository, pr_data)

    git_account.last_synced_at = timezone.now()
    git_account.save(update_fields=['last_synced_at'])


def auto_sync_gitlab_account(git_account):
    token = git_account.access_token
    since_iso = _start_of_today().isoformat()

    for repo_data in gitlab.iter_repositories(token):
        repository = _upsert_repository_from_gitlab(git_account, repo_data)

        for commit_data in gitlab.iter_commits(token, repo_data['id'], since=since_iso):
            commit, created = _upsert_gitlab_commit(repository, commit_data)
            if created or not commit.files.exists():
                _sync_gitlab_commit_files(git_account, commit, repo_data['id'], commit_data['id'])

        for mr_data in gitlab.iter_merge_requests(token, repo_data['id'], updated_after=since_iso):
            _upsert_gitlab_merge_request(repository, mr_data)

    git_account.last_synced_at = timezone.now()
    git_account.save(update_fields=['last_synced_at'])


def auto_sync_account(git_account):
    if git_account.provider == GitAccount.Provider.GITHUB:
        auto_sync_github_account(git_account)
    elif git_account.provider == GitAccount.Provider.GITLAB:
        auto_sync_gitlab_account(git_account)
    else:
        raise ValueError(f'Unknown provider: {git_account.provider}')


def auto_sync_all_git_accounts():
    """Auto-sync every connected account, today's commits/merge requests only.
    Runs synchronously — used as the fallback path when Celery isn't available
    (e.g. `manage.py sync_git_data --auto`). The scheduled path instead fans out
    one Celery task per account; see integrations/tasks.py."""
    synced, failed = 0, 0
    for git_account in GitAccount.objects.all():
        try:
            auto_sync_account(git_account)
        except Exception:
            failed += 1
            logger.exception('Auto sync failed for %s', git_account)
        else:
            synced += 1
    logger.info('Auto git sync finished: %s succeeded, %s failed', synced, failed)
    return {'synced': synced, 'failed': failed}
