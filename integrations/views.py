import base64
from datetime import date, timedelta

import requests
from django.core import signing
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from integrations.models import Commit, CommitFile, GitAccount, MergeRequest, Repository
from integrations.serializers import (
    CommitReviewSerializer,
    CommitSerializer,
    GitAccountSerializer,
    MergeRequestReviewSerializer,
    MergeRequestSerializer,
    RepositorySerializer,
)
from integrations.services import github, gitlab
from integrations.services.languages import calculate_language_stats
from integrations.services.sync import sync_account, sync_all_accounts_for_user
from rest_framework.authentication import (
                                    BasicAuthentication,
                                    SessionAuthentication)
from rest_framework.permissions import (
                                        IsAdminUser,
                                        AllowAny,
                                        IsAuthenticated)
from accounts.token_authentication import TokenAuthentication

STATE_SALT = 'integrations.oauth.state'
STATE_MAX_AGE = 300  # seconds


def _make_state(user_id):
    return signing.dumps({'user_id': str(user_id)}, salt=STATE_SALT)


def _read_state(state):
    data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    return data['user_id']


class GitHubConnectView(APIView):
    """Step 1: authenticated user asks for the URL to redirect their browser to."""

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        state = _make_state(request.user.id)
        return Response({'authorize_url': github.get_authorize_url(state)})


class GitHubCallbackView(APIView):
    """Step 2: GitHub redirects the browser here with ?code=...&state=..."""

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        if not code or not state:
            raise ValidationError('Missing code or state.')

        try:
            user_id = _read_state(state)
        except signing.BadSignature:
            raise ValidationError('Invalid or expired state.')

        token_data = github.exchange_code_for_token(code)
        profile = github.get_authenticated_user(token_data['access_token'])

        git_account, _ = GitAccount.objects.update_or_create(
            user_id=user_id,
            provider=GitAccount.Provider.GITHUB,
            defaults={
                'provider_user_id': str(profile['id']),
                'username': profile['login'],
                'avatar_url': profile.get('avatar_url', ''),
                'profile_url': profile.get('html_url', ''),
                'access_token': token_data['access_token'],
            },
        )
        return Response(GitAccountSerializer(git_account).data)


class GitLabConnectView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request):
        state = _make_state(request.user.id)
        return Response({'authorize_url': gitlab.get_authorize_url(state)})


class GitLabCallbackView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        if not code or not state:
            raise ValidationError('Missing code or state.')

        try:
            user_id = _read_state(state)
        except signing.BadSignature:
            raise ValidationError('Invalid or expired state.')

        token_data = gitlab.exchange_code_for_token(code)
        profile = gitlab.get_authenticated_user(token_data['access_token'])

        git_account, _ = GitAccount.objects.update_or_create(
            user_id=user_id,
            provider=GitAccount.Provider.GITLAB,
            defaults={
                'provider_user_id': str(profile['id']),
                'username': profile['username'],
                'avatar_url': profile.get('avatar_url', ''),
                'profile_url': profile.get('web_url', ''),
                'access_token': token_data['access_token'],
                'refresh_token': token_data.get('refresh_token', ''),
            },
        )
        return Response(GitAccountSerializer(git_account).data)


class GitAccountListView(generics.ListAPIView):
    serializer_class = GitAccountSerializer
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.request.user.git_accounts.all()


class SyncView(APIView):
    """Pull all repos + commits for every git account the current user has connected."""

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        provider = request.data.get('provider')
        accounts = request.user.git_accounts.all()
        if provider:
            accounts = accounts.filter(provider=provider)
            if not accounts.exists():
                raise ValidationError(f'No connected {provider} account.')

        synced = []
        for git_account in accounts:
            sync_account(git_account)
            synced.append(git_account)

        return Response(
            {
                'synced_accounts': GitAccountSerializer(synced, many=True).data,
                'repository_count': Repository.objects.filter(
                    git_account__in=synced
                ).count(),
            }
        )


class RepositoryListView(generics.ListAPIView):
    serializer_class = RepositorySerializer
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Repository.objects.filter(git_account__user=self.request.user)


class RepositoryCommitListView(generics.ListAPIView):
    serializer_class = CommitSerializer
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        repository = get_object_or_404(
            Repository, id=self.kwargs['repository_id'], git_account__user=self.request.user
        )
        return repository.commits.prefetch_related('files')


class CommitListView(generics.ListAPIView):
    """Staff see every commit (for review); regular users see only their own repos' commits."""

    serializer_class = CommitSerializer
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Commit.objects.select_related(
            'repository', 'repository__git_account'
        ).prefetch_related('files')
        if not self.request.user.is_staff:
            queryset = queryset.filter(repository__git_account__user=self.request.user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset


class CommitReviewView(APIView):
    """Staff-only: mark a commit as approved or rejected."""

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, commit_id):
        commit = get_object_or_404(Commit, id=commit_id)
        serializer = CommitReviewSerializer(commit, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(reviewed_by=request.user, reviewed_at=timezone.now())
        return Response(CommitSerializer(commit).data, status=status.HTTP_200_OK)



class CommitCalendarView(APIView):
    """GitHub-profile-style commit calendar: one entry per day with a commit count
    and a colour intensity level, computed entirely from already-synced local data
    (no extra GitHub/GitLab API calls, so no external rate limits or latency).

    Query params:
      - repository_id: restrict to one repository (must belong to the user)
      - provider: 'github' or 'gitlab', restrict to accounts of that provider
      - year: calendar year (Jan 1 - Dec 31); defaults to the trailing 365 days
    """

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    # Same 5-shade palette GitHub uses for its contribution graph (light theme).
    LEVEL_COLORS = {
        0: '#ebedf0',
        1: '#9be9a8',
        2: '#40c463',
        3: '#30a14e',
        4: '#216e39',
    }
    # Upper bound of daily commit count -> level. Above the last bucket caps at level 4.
    LEVEL_THRESHOLDS = (1, 3, 6, 10)

    def get(self, request):
        queryset = Commit.objects.filter(repository__git_account__user=request.user)

        provider = request.query_params.get('provider')
        if provider:
            queryset = queryset.filter(repository__git_account__provider=provider)

        repository_id = request.query_params.get('repository_id')
        if repository_id:
            get_object_or_404(Repository, id=repository_id, git_account__user=request.user)
            queryset = queryset.filter(repository_id=repository_id)

        year = request.query_params.get('year')
        if year:
            try:
                year = int(year)
            except ValueError:
                raise ValidationError('year must be an integer.')
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
        else:
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=364)

        queryset = queryset.filter(authored_at__date__gte=start_date, authored_at__date__lte=end_date)

        counts_by_day = dict(
            queryset.annotate(day=TruncDate('authored_at'))
            .values('day')
            .annotate(count=Count('id'))
            .values_list('day', 'count')
        )

        days = []
        current = start_date
        while current <= end_date:
            count = counts_by_day.get(current, 0)
            level = self._level_for_count(count)
            days.append(
                {
                    'date': current.isoformat(),
                    'count': count,
                    'level': level,
                    'color': self.LEVEL_COLORS[level],
                }
            )
            current += timedelta(days=1)

        return Response(
            {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'total_commits': sum(day['count'] for day in days),
                'levels': self.LEVEL_COLORS,
                'days': days,
            }
        )

    @classmethod
    def _level_for_count(cls, count):
        if count == 0:
            return 0
        for level, threshold in enumerate(cls.LEVEL_THRESHOLDS, start=1):
            if count <= threshold:
                return level
        return len(cls.LEVEL_THRESHOLDS)


class RepositoryBranchListView(APIView):
    """Per-branch ahead/behind counts vs. the repository's default branch — the same
    numbers GitLab/GitHub show on their own branches pages. Computed live against the
    provider API on every request (not stored locally), so it's always current."""

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, repository_id):
        repository = get_object_or_404(
            Repository, id=repository_id, git_account__user=request.user
        )
        git_account = repository.git_account
        default_branch = repository.default_branch
        print("RepositoryBranchListView: repository_id:", repository_id, "default_branch:", default_branch)
        print("git_account:", git_account, "provider:", git_account.provider, "access_token:", git_account.access_token)

        if git_account.provider == GitAccount.Provider.GITLAB:
            branches = self._gitlab_branch_status(git_account, repository, default_branch)
        else:
            branches = self._github_branch_status(git_account, repository, default_branch)

        return Response({'default_branch': default_branch, 'branches': branches})

    @staticmethod
    def _gitlab_branch_status(git_account, repository, default_branch):
        token = git_account.access_token
        project_id = repository.provider_repo_id
        print("RepositoryBranchListView: _gitlab_branch_status: project_id:", project_id, "default_branch:", default_branch)
        print("RepositoryBranchListView: _gitlab_branch_status: token:", token)
        results = []
        try:
            for branch in gitlab.iter_branches(token, project_id):
                name = branch['name']
                is_default = name == default_branch
                ahead = behind = 0
                if not is_default:
                    ahead = len(gitlab.compare_refs(token, project_id, default_branch, name))
                    behind = len(gitlab.compare_refs(token, project_id, name, default_branch))
                results.append(
                    {
                        'name': name,
                        'is_default': is_default,
                        'merged': branch.get('merged', False),
                        'protected': branch.get('protected', False),
                        'ahead_by': ahead,
                        'behind_by': behind,
                    }
                )
            return results
        except requests.HTTPError as exc:
            raise ValidationError(f'Failed to fetch branches from GitLab: {exc}')
        
    @staticmethod
    def _github_branch_status(git_account, repository, default_branch):
        token = git_account.access_token
        owner, name = repository.full_name.split('/', 1)
        results = []
        for branch in github.iter_branches(token, owner, name):
            branch_name = branch['name']
            is_default = branch_name == default_branch
            ahead = behind = 0
            if not is_default:
                comparison = github.compare_commits(token, owner, name, default_branch, branch_name)
                ahead = comparison.get('ahead_by', 0)
                behind = comparison.get('behind_by', 0)
            results.append(
                {
                    'name': branch_name,
                    'is_default': is_default,
                    'protected': branch.get('protected', False),
                    'ahead_by': ahead,
                    'behind_by': behind,
                }
            )
        return results


class RepositoryTreeView(APIView):
    """Browse a repository's file tree, GitHub/GitLab-browser style: click into the
    repository and see its root files/folders, click a folder to see what's inside.
    Fetched live from the provider on every call (not stored locally), so it's
    always current and needs no extra sync/storage.

    Query params:
      - path: folder to list, relative to repo root (default: '' = root)
      - ref: branch/commit to read from (default: the repository's default branch)
    """

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, repository_id):
        repository = get_object_or_404(
            Repository, id=repository_id, git_account__user=request.user
        )
        path = request.query_params.get('path', '').strip('/')
        ref = request.query_params.get('ref') or repository.default_branch
        git_account = repository.git_account

        try:
            if git_account.provider == GitAccount.Provider.GITLAB:
                items = self._gitlab_tree(git_account, repository, path, ref)
            else:
                items = self._github_tree(git_account, repository, path, ref)
        except requests.HTTPError as exc:
            raise ValidationError(f'Failed to fetch repository tree: {exc}')

        return Response({'path': path, 'ref': ref, 'items': items})

    @staticmethod
    def _github_tree(git_account, repository, path, ref):
        owner, name = repository.full_name.split('/', 1)
        contents = github.get_contents(git_account.access_token, owner, name, path, ref)
        if isinstance(contents, dict):
            # `path` pointed straight at a file rather than a directory.
            contents = [contents]
        return [
            {
                'name': item['name'],
                'path': item['path'],
                'type': 'dir' if item['type'] == 'dir' else 'file',
                'size': item.get('size'),
            }
            for item in contents
        ]

    @staticmethod
    def _gitlab_tree(git_account, repository, path, ref):
        items = gitlab.list_tree(git_account.access_token, repository.provider_repo_id, path, ref)
        return [
            {
                'name': item['name'],
                'path': item['path'],
                'type': 'dir' if item['type'] == 'tree' else 'file',
                'size': None,
            }
            for item in items
        ]


class RepositoryFileContentView(APIView):
    """Fetch a single file's content at a given path/ref, for viewing after the user
    clicks a file in the tree browser. Fetched live from the provider."""

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, repository_id):
        repository = get_object_or_404(
            Repository, id=repository_id, git_account__user=request.user
        )
        path = request.query_params.get('path', '').strip('/')
        if not path:
            raise ValidationError('path query param is required.')
        ref = request.query_params.get('ref') or repository.default_branch
        if not ref:
            raise ValidationError('No ref provided and repository has no default_branch on record.')
        git_account = repository.git_account

        try:
            if git_account.provider == GitAccount.Provider.GITLAB:
                raw = gitlab.get_file(git_account.access_token, repository.provider_repo_id, path, ref)
            else:
                owner, name = repository.full_name.split('/', 1)
                raw = github.get_contents(git_account.access_token, owner, name, path, ref)
                if isinstance(raw, list):
                    raise ValidationError('path points to a directory, not a file.')
        except requests.HTTPError as exc:
            raise ValidationError(f'Failed to fetch file: {exc}')

        encoded_content = raw.get('content', '')
        content_bytes = base64.b64decode(encoded_content) if encoded_content else b''
        try:
            content, binary = content_bytes.decode('utf-8'), False
        except UnicodeDecodeError:
            content, binary = base64.b64encode(content_bytes).decode('ascii'), True

        return Response(
            {
                'path': path,
                'ref': ref,
                'size': raw.get('size'),
                'binary': binary,
                'content': content,
            }
        )


class RepositoryLanguageStatsView(APIView):
    """GitHub-style language bar for one repository — e.g. Python 50%, HTML 10%,
    JavaScript 30%. Computed entirely from already-synced CommitFile rows (no extra
    GitHub/GitLab API calls), so it updates automatically after every sync."""

    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, repository_id):
        repository = get_object_or_404(
            Repository, id=repository_id, git_account__user=request.user
        )
        commit_files = CommitFile.objects.filter(commit__repository=repository)
        languages = calculate_language_stats(commit_files)

        return Response({'repository': repository.full_name, 'languages': languages})


class RepositoryMergeRequestListView(generics.ListAPIView):
    """Merge requests (PRs/MRs) synced for one repository the current user owns."""

    serializer_class = MergeRequestSerializer
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        repository = get_object_or_404(
            Repository, id=self.kwargs['repository_id'], git_account__user=self.request.user
        )
        return repository.merge_requests.all()


class MergeRequestListView(generics.ListAPIView):
    """Staff see every merge request (for review); regular users see only their own repos'."""

    serializer_class = MergeRequestSerializer
    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = MergeRequest.objects.select_related('repository', 'repository__git_account')
        if not self.request.user.is_staff:
            queryset = queryset.filter(repository__git_account__user=self.request.user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset


class MergeRequestReviewView(APIView):
    """Staff-only: verify a merge request and accept (merge), reject, or close it.

    'merge' and 'close' call out to the real GitHub/GitLab API so the provider-side
    PR/MR actually gets merged or closed — this isn't just a local status flag.
    """


    authentication_classes = [SessionAuthentication, BasicAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, merge_request_id):
        merge_request = get_object_or_404(MergeRequest, id=merge_request_id)
        serializer = MergeRequestReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']
        review_notes = serializer.validated_data['review_notes']

        git_account = merge_request.repository.git_account

        try:
            if action == 'merge':
                self._merge_on_provider(git_account, merge_request)
                new_status = MergeRequest.Status.APPROVED
                new_provider_state = MergeRequest.ProviderState.MERGED
            elif action == 'close':
                self._close_on_provider(git_account, merge_request)
                new_status = MergeRequest.Status.CLOSED
                new_provider_state = MergeRequest.ProviderState.CLOSED
            else:  # reject — internal review decision only, provider PR/MR is left as-is
                new_status = MergeRequest.Status.REJECTED
                new_provider_state = merge_request.provider_state
        except requests.HTTPError as exc:
            raise ValidationError(f'{action} failed on the provider: {exc}')

        merge_request.status = new_status
        merge_request.provider_state = new_provider_state
        merge_request.reviewed_by = request.user
        merge_request.reviewed_at = timezone.now()
        merge_request.review_notes = review_notes
        merge_request.save()

        return Response(MergeRequestSerializer(merge_request).data, status=status.HTTP_200_OK)

    @staticmethod
    def _merge_on_provider(git_account, merge_request):
        repository = merge_request.repository
        if git_account.provider == GitAccount.Provider.GITHUB:
            owner, name = repository.full_name.split('/', 1)
            github.merge_pull_request(
                git_account.access_token, owner, name, merge_request.provider_mr_id
            )
        else:
            gitlab.merge_merge_request(
                git_account.access_token, repository.provider_repo_id, merge_request.provider_mr_id
            )

    @staticmethod
    def _close_on_provider(git_account, merge_request):
        repository = merge_request.repository
        if git_account.provider == GitAccount.Provider.GITHUB:
            owner, name = repository.full_name.split('/', 1)
            github.close_pull_request(
                git_account.access_token, owner, name, merge_request.provider_mr_id
            )
        else:
            gitlab.close_merge_request(
                git_account.access_token, repository.provider_repo_id, merge_request.provider_mr_id
            )
