from urllib.parse import urlencode

import requests
from django.conf import settings

GITLAB_BASE = 'https://gitlab.com'
AUTHORIZE_URL = f'{GITLAB_BASE}/oauth/authorize'
TOKEN_URL = f'{GITLAB_BASE}/oauth/token'
API_URL = f'{GITLAB_BASE}/api/v4'


def get_authorize_url(state):
    params = {
        'client_id': settings.GITLAB_CLIENT_ID,
        'redirect_uri': settings.GITLAB_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'read_user read_api api',
        'state': state,
    }
    return f'{AUTHORIZE_URL}?{urlencode(params)}'


def exchange_code_for_token(code):
    response = requests.post(
        TOKEN_URL,
        data={
            'client_id': settings.GITLAB_CLIENT_ID,
            'client_secret': settings.GITLAB_CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': settings.GITLAB_REDIRECT_URI,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()  # {'access_token': ..., 'refresh_token': ..., 'expires_in': ...}


def _headers(access_token):
    return {'Authorization': f'Bearer {access_token}'}


def get_authenticated_user(access_token):
    response = requests.get(f'{API_URL}/user', headers=_headers(access_token), timeout=10)
    response.raise_for_status()
    return response.json()


def iter_repositories(access_token):
    page = 1
    while True:
        response = requests.get(
            f'{API_URL}/projects',
            headers=_headers(access_token),
            params={'membership': True, 'per_page': 100, 'page': page},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        yield from items
        page += 1


def iter_branches(access_token, project_id):
    page = 1
    while True:
        response = requests.get(
            f'{API_URL}/projects/{project_id}/repository/branches',
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


def compare_refs(access_token, project_id, from_ref, to_ref):
    """Commits reachable from `to_ref` but not `from_ref`. Called both ways round to
    get ahead/behind counts — GitLab's compare endpoint has no single ahead/behind field,
    unlike GitHub's."""
    response = requests.get(
        f'{API_URL}/projects/{project_id}/repository/compare',
        headers=_headers(access_token),
        params={'from': from_ref, 'to': to_ref},
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get('commits', [])


def get_commit_diff(access_token, project_id, sha):
    """Diff endpoint — the only one that includes the changed-files list."""
    response = requests.get(
        f'{API_URL}/projects/{project_id}/repository/commits/{sha}/diff',
        headers=_headers(access_token),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def iter_commits(access_token, project_id, since=None):
    """`since` (ISO8601 string) restricts results to commits made after that time —
    used by auto-sync to pull only today's commits instead of full history."""
    page = 1
    params = {'per_page': 100, 'with_stats': True}
    if since:
        params['since'] = since
    while True:
        response = requests.get(
            f'{API_URL}/projects/{project_id}/repository/commits',
            headers=_headers(access_token),
            params={**params, 'page': page},
            timeout=15,
        )
        if response.status_code == 404:
            break
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        yield from items
        page += 1


def iter_merge_requests(access_token, project_id, updated_after=None):
    """`updated_after` (ISO8601 string) restricts results to MRs updated after that time —
    used by auto-sync to pull only today's merge requests instead of full history."""
    page = 1
    params = {'state': 'all', 'per_page': 100}
    if updated_after:
        params['updated_after'] = updated_after
        params['order_by'] = 'updated_at'
        params['sort'] = 'desc'
    while True:
        response = requests.get(
            f'{API_URL}/projects/{project_id}/merge_requests',
            headers=_headers(access_token),
            params={**params, 'page': page},
            timeout=15,
        )
        if response.status_code == 404:
            break
        response.raise_for_status()
        items = response.json()
        if not items:
            break
        yield from items
        page += 1


def merge_merge_request(access_token, project_id, merge_iid):
    """Actually merges the MR on GitLab. Raises requests.HTTPError if it can't be merged
    (e.g. conflicts, unresolved discussions, pipeline not passing)."""
    response = requests.put(
        f'{API_URL}/projects/{project_id}/merge_requests/{merge_iid}/merge',
        headers=_headers(access_token),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def close_merge_request(access_token, project_id, merge_iid):
    """Closes the MR on GitLab without merging it."""
    response = requests.put(
        f'{API_URL}/projects/{project_id}/merge_requests/{merge_iid}',
        headers=_headers(access_token),
        json={'state_event': 'close'},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()
