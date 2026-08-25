import uuid

from django.conf import settings
from django.db import models


class GitAccount(models.Model):
    """A user's connection to a GitHub or GitLab account (OAuth)."""

    class Provider(models.TextChoices):
        GITHUB = 'github', 'GitHub'
        GITLAB = 'gitlab', 'GitLab'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='git_accounts'
    )
    provider = models.CharField(max_length=10, choices=Provider.choices)

    provider_user_id = models.CharField(max_length=64)
    username = models.CharField(max_length=255)
    avatar_url = models.URLField(blank=True)
    profile_url = models.URLField(blank=True)

    access_token = models.TextField()
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    connected_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'provider'], name='unique_user_provider'),
        ]

    def __str__(self):
        return f'{self.user} / {self.provider}:{self.username}'


class Repository(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    git_account = models.ForeignKey(
        GitAccount, on_delete=models.CASCADE, related_name='repositories'
    )

    provider_repo_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    full_name = models.CharField(max_length=512)
    description = models.TextField(blank=True)
    url = models.URLField()
    default_branch = models.CharField(max_length=255, blank=True)
    is_private = models.BooleanField(default=False)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['git_account', 'provider_repo_id'], name='unique_account_repo'
            ),
        ]
        verbose_name_plural = 'repositories'

    def __str__(self):
        return self.full_name


class Commit(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='commits')

    sha = models.CharField(max_length=64)
    message = models.TextField()
    author_name = models.CharField(max_length=255, blank=True)
    author_email = models.EmailField(blank=True)
    authored_at = models.DateTimeField(null=True, blank=True)
    url = models.URLField(blank=True)

    additions = models.PositiveIntegerField(null=True, blank=True)
    deletions = models.PositiveIntegerField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_commits',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['repository', 'sha'], name='unique_repo_commit'),
        ]
        ordering = ['-authored_at']
        indexes = [
            models.Index(fields=['repository', 'authored_at'], name='commit_repo_authored_idx'),
        ]

    def __str__(self):
        return f'{self.repository.name}@{self.sha[:7]}'


class MergeRequest(models.Model):
    """A pull request (GitHub) or merge request (GitLab) synced from the provider."""

    class ProviderState(models.TextChoices):
        OPEN = 'open', 'Open'
        CLOSED = 'closed', 'Closed'
        MERGED = 'merged', 'Merged'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        APPROVED = 'approved', 'Approved (merged)'
        REJECTED = 'rejected', 'Rejected'
        CLOSED = 'closed', 'Closed without merging'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, related_name='merge_requests'
    )

    provider_mr_id = models.CharField(max_length=64)  # GitHub PR number / GitLab MR iid
    title = models.CharField(max_length=1024)
    description = models.TextField(blank=True)
    author_name = models.CharField(max_length=255, blank=True)
    source_branch = models.CharField(max_length=255, blank=True)
    target_branch = models.CharField(max_length=255, blank=True)
    url = models.URLField(blank=True)

    provider_state = models.CharField(
        max_length=10, choices=ProviderState.choices, default=ProviderState.OPEN
    )
    provider_created_at = models.DateTimeField(null=True, blank=True)
    provider_updated_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_merge_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['repository', 'provider_mr_id'], name='unique_repo_merge_request'
            ),
        ]
        ordering = ['-provider_created_at']

    def __str__(self):
        return f'{self.repository.name}!{self.provider_mr_id}'


class CommitFile(models.Model):
    """One changed file within a commit (which file, what happened to it, the diff)."""

    class ChangeType(models.TextChoices):
        ADDED = 'added', 'Added'
        MODIFIED = 'modified', 'Modified'
        REMOVED = 'removed', 'Removed'
        RENAMED = 'renamed', 'Renamed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commit = models.ForeignKey(Commit, on_delete=models.CASCADE, related_name='files')

    filename = models.CharField(max_length=1024)
    status = models.CharField(max_length=10, choices=ChangeType.choices, blank=True)
    additions = models.PositiveIntegerField(null=True, blank=True)
    deletions = models.PositiveIntegerField(null=True, blank=True)
    patch = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['commit', 'filename'], name='unique_commit_file'),
        ]

    def __str__(self):
        return f'{self.commit}: {self.filename}'
