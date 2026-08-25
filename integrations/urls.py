from django.urls import path

from integrations.views import (
    CommitCalendarView,
    CommitListView,
    CommitReviewView,
    GitAccountListView,
    GitHubCallbackView,
    GitHubConnectView,
    GitLabCallbackView,
    GitLabConnectView,
    MergeRequestListView,
    MergeRequestReviewView,
    RepositoryBranchListView,
    RepositoryCommitListView,
    RepositoryFileContentView,
    RepositoryLanguageStatsView,
    RepositoryListView,
    RepositoryMergeRequestListView,
    RepositoryTreeView,
    SyncView,
    AutoSyncView,
)

app_name = 'integrations'

urlpatterns = [
    path('accounts/', GitAccountListView.as_view()),        # List the current user's connected GitHub/GitLab accounts
    path('github/connect/', GitHubConnectView.as_view()),       # Get the GitHub OAuth authorize URL to redirect the user's browser to
    path('github/callback/', GitHubCallbackView.as_view()),     # GitHub OAuth redirects here with ?code=&state= to complete the connection
    path('gitlab/connect/', GitLabConnectView.as_view()),       # Get the GitLab OAuth authorize URL to redirect the user's browser to
    path('gitlab/callback/', GitLabCallbackView.as_view()),     # GitLab OAuth redirects here with ?code=&state= to complete the connection
    path('sync/', SyncView.as_view()),      # Trigger a full manual sync of repos/commits/merge requests for the current user
    path('repositories/', RepositoryListView.as_view()),        # List every repository synced for the current user
    path('repositories/<uuid:repository_id>/commits/',RepositoryCommitListView.as_view()),      # List commits belonging to one specific repository
    path('repositories/<uuid:repository_id>/branches/',RepositoryBranchListView.as_view()),      # Per-branch ahead/behind status vs. the default branch (live from the provider API)
    path('repositories/<uuid:repository_id>/languages/',RepositoryLanguageStatsView.as_view()),      # Language breakdown (%) for one repository, computed from synced commit files
    path('repositories/<uuid:repository_id>/tree/',RepositoryTreeView.as_view()),      # Browse files/folders at a path+ref (live from the provider) — click a folder to list its contents
    path('repositories/<uuid:repository_id>/file/',RepositoryFileContentView.as_view()),      # Fetch one file's content at a path+ref — click a file to view it
    path('commits/', CommitListView.as_view()),     # List commits (all for staff, own repos only for regular users)
    path('commits/calendar/', CommitCalendarView.as_view()),        # GitHub-style daily commit calendar with counts and colour intensity levels
    path('commits/<uuid:commit_id>/review/', CommitReviewView.as_view()),       # Staff-only: approve or reject a single commit
    path('repositories/<uuid:repository_id>/merge-requests/',RepositoryMergeRequestListView.as_view()),     # List merge requests (PRs/MRs) belonging to one specific repository
    path('merge-requests/', MergeRequestListView.as_view()),        # List merge requests (all for staff, own repos only for regular users)
    path('merge-requests/<uuid:merge_request_id>/review/',MergeRequestReviewView.as_view()),        # Staff-only: merge, reject, or close a single merge request
    path('auto-sync/',AutoSyncView.as_view()),      # Trigger a full auto-sync of repos/commits/merge requests for the current user
]
