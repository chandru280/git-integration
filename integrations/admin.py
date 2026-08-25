from django.contrib import admin

from integrations.models import Commit, CommitFile, GitAccount, MergeRequest, Repository


@admin.register(GitAccount)
class GitAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'provider', 'username', 'connected_at', 'last_synced_at')
    list_filter = ('provider',)
    search_fields = ('username', 'user__email')


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'git_account', 'is_private', 'last_synced_at')
    list_filter = ('is_private',)
    search_fields = ('full_name', 'name')


@admin.register(Commit)
class CommitAdmin(admin.ModelAdmin):
    list_display = ('repository', 'sha', 'status', 'author_name', 'authored_at', 'reviewed_by')
    list_filter = ('status', 'repository')
    search_fields = ('sha', 'message', 'author_name')
    readonly_fields = ('repository', 'sha', 'message', 'author_name', 'author_email', 'authored_at', 'url')


@admin.register(CommitFile)
class CommitFileAdmin(admin.ModelAdmin):
    list_display = ('commit', 'filename', 'status', 'additions', 'deletions')
    list_filter = ('status',)
    search_fields = ('filename',)
    readonly_fields = ('commit', 'filename', 'status', 'additions', 'deletions', 'patch')


@admin.register(MergeRequest)
class MergeRequestAdmin(admin.ModelAdmin):
    list_display = (
        'repository', 'provider_mr_id', 'title', 'provider_state', 'status', 'reviewed_by',
    )
    list_filter = ('status', 'provider_state', 'repository')
    search_fields = ('title', 'provider_mr_id', 'author_name')
    readonly_fields = (
        'repository', 'provider_mr_id', 'title', 'description', 'author_name',
        'source_branch', 'target_branch', 'url', 'provider_state',
        'provider_created_at', 'provider_updated_at',
    )
