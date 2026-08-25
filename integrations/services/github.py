from urllib.parse import urlencode

import requests
from django.conf import settings

AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
TOKEN_URL = 'https://github.com/login/oauth/access_token'
API_URL = 'https://api.github.com'


def get_authorize_url(state):
    params = {
        'client_id': settings.GITHUB_CLIENT_ID,
        'redirect_uri': settings.GITHUB_REDIRECT_URI,
        'scope': 'read:user repo',
        'state': state,
    }
    return f'{AUTHORIZE_URL}?{urlencode(params)}'


def exchange_code_for_token(code):
    response = requests.post(
        TOKEN_URL,
        data={
            'client_id': settings.GITHUB_CLIENT_ID,
            'client_secret': settings.GITHUB_CLIENT_SECRET,
            'code': code,
            'redirect_uri': settings.GITHUB_REDIRECT_URI,
        },
        headers={'Accept': 'application/json'},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if 'error' in data:
        raise ValueError(data.get('error_description', data['error']))
    return data  # {'access_token': ..., 'scope': ..., 'token_type': ...}


def _headers(access_token):
    return {
        'Authorization': f'token {access_token}',
        'Accept': 'application/vnd.github+json',
    }


def get_authenticated_user(access_token):
    response = requests.get(f'{API_URL}/user', headers=_headers(access_token), timeout=10)
    response.raise_for_status()
    return response.json()


def iter_repositories(access_token):
    page = 1
    while True:
        response = requests.get(
            f'{API_URL}/user/repos',
            headers=_headers(access_token),
            params={'per_page': 100, 'page': page, 'affiliation': 'owner,collaborator'},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        yield from items
        page += 1


def iter_branches(access_token, owner, repo):
    page = 1
    while True:
        response = requests.get(
            f'{API_URL}/repos/{owner}/{repo}/branches',
            headers=_headers(access_token),
            params={'per_page': 100, 'page': page},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        yield from items
        page += 1


def compare_commits(access_token, owner, repo, base, head):
    """`ahead_by`/`behind_by` come straight from this endpoint — GitHub computes both
    directions in one call, unlike GitLab's compare endpoint."""
    response = requests.get(
        f'{API_URL}/repos/{owner}/{repo}/compare/{base}...{head}',
        headers=_headers(access_token),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_commit_detail(access_token, owner, repo, sha):
    """Single-commit endpoint — the only one that includes the changed-files list."""
    response = requests.get(
        f'{API_URL}/repos/{owner}/{repo}/commits/{sha}',
        headers=_headers(access_token),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def iter_commits(access_token, owner, repo, since=None):
    """`since` (ISO8601 string) restricts results to commits authored after that time —
    used by auto-sync to pull only today's commits instead of full history."""
    page = 1
    params = {'per_page': 100}
    if since:
        params['since'] = since
    while True:
        response = requests.get(
            f'{API_URL}/repos/{owner}/{repo}/commits',
            headers=_headers(access_token),
            params={**params, 'page': page},
            timeout=15,
        )
        if response.status_code == 409:
            # Empty repository (no commits yet)
            break
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        yield from items
        page += 1


def iter_pull_requests(access_token, owner, repo, sort='created', direction='desc'):
    """GitHub's PR list has no date filter, so callers that only want recent PRs (auto-sync)
    should pass sort='updated' and stop iterating once results get too old."""
    page = 1
    while True:
        response = requests.get(
            f'{API_URL}/repos/{owner}/{repo}/pulls',
            headers=_headers(access_token),
            params={
                'state': 'all',
                'sort': sort,
                'direction': direction,
                'per_page': 100,
                'page': page,
            },
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        yield from items
        page += 1


def merge_pull_request(access_token, owner, repo, number, commit_message=''):
    """Actually merges the PR on GitHub. Raises requests.HTTPError if it can't be merged
    (e.g. conflicts, failing required checks, branch protection)."""
    payload = {}
    if commit_message:
        payload['commit_message'] = commit_message
    response = requests.put(
        f'{API_URL}/repos/{owner}/{repo}/pulls/{number}/merge',
        headers=_headers(access_token),
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def close_pull_request(access_token, owner, repo, number):
    """Closes the PR on GitHub without merging it."""
    response = requests.patch(
        f'{API_URL}/repos/{owner}/{repo}/pulls/{number}',
        headers=_headers(access_token),
        json={'state': 'closed'},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()
