import os

# Maps file extensions (lowercase, with leading dot) to a human-readable language name.
EXTENSION_LANGUAGE_MAP = {
    '.py': 'Python',
    '.pyi': 'Python',
    '.ipynb': 'Jupyter Notebook',
    '.js': 'JavaScript',
    '.jsx': 'JavaScript',
    '.mjs': 'JavaScript',
    '.cjs': 'JavaScript',
    '.ts': 'TypeScript',
    '.tsx': 'TypeScript',
    '.html': 'HTML',
    '.htm': 'HTML',
    '.css': 'CSS',
    '.scss': 'SCSS',
    '.sass': 'Sass',
    '.less': 'Less',
    '.java': 'Java',
    '.kt': 'Kotlin',
    '.kts': 'Kotlin',
    '.go': 'Go',
    '.rb': 'Ruby',
    '.php': 'PHP',
    '.c': 'C',
    '.h': 'C',
    '.cpp': 'C++',
    '.cc': 'C++',
    '.cxx': 'C++',
    '.hpp': 'C++',
    '.cs': 'C#',
    '.swift': 'Swift',
    '.m': 'Objective-C',
    '.mm': 'Objective-C',
    '.sh': 'Shell',
    '.bash': 'Shell',
    '.zsh': 'Shell',
    '.sql': 'SQL',
    '.json': 'JSON',
    '.yml': 'YAML',
    '.yaml': 'YAML',
    '.md': 'Markdown',
    '.rst': 'reStructuredText',
    '.xml': 'XML',
    '.vue': 'Vue',
    '.dart': 'Dart',
    '.rs': 'Rust',
    '.scala': 'Scala',
    '.pl': 'Perl',
    '.lua': 'Lua',
    '.r': 'R',
    '.ex': 'Elixir',
    '.exs': 'Elixir',
    '.erl': 'Erlang',
    '.clj': 'Clojure',
    '.groovy': 'Groovy',
    '.ps1': 'PowerShell',
    '.bat': 'Batch',
    '.toml': 'TOML',
    '.ini': 'INI',
    '.cfg': 'INI',
}

# Extension-less filenames matched case-insensitively straight to a language.
FILENAME_LANGUAGE_MAP = {
    'dockerfile': 'Dockerfile',
    'makefile': 'Makefile',
    'rakefile': 'Ruby',
    'gemfile': 'Ruby',
}

# Lockfiles named by convention rather than extension — always machine-generated.
IGNORED_FILENAMES = {
    'package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock', 'pnpm-lock.yaml',
    'composer.lock', 'pipfile.lock', 'poetry.lock', 'cargo.lock', 'gemfile.lock',
}

# Generated output and binaries — excluded so they don't skew the breakdown.
IGNORED_SUFFIXES = (
    '.lock', '.min.js', '.min.css', '.map', '.png', '.jpg', '.jpeg', '.gif', '.svg',
    '.ico', '.woff', '.woff2', '.ttf', '.eot', '.pdf', '.zip', '.gz', '.pyc', '.so',
    '.o', '.class', '.jar', '.exe',
)


def detect_language(filename):
    """Return the language name for a filename, or None if it should be excluded
    from language statistics (binary, generated, or unrecognized)."""
    base = os.path.basename(filename).lower()

    if base in IGNORED_FILENAMES:
        return None

    if base in FILENAME_LANGUAGE_MAP:
        return FILENAME_LANGUAGE_MAP[base]

    if base.endswith(IGNORED_SUFFIXES):
        return None

    _, ext = os.path.splitext(base)
    return EXTENSION_LANGUAGE_MAP.get(ext)


def _file_weight(commit_file):
    """Lines changed is the fairest proxy for "how much of this language was written."
    Falls back to a flat weight of 1 when line counts weren't captured (GitLab file
    diffs don't currently store additions/deletions), so the file still counts instead
    of vanishing from the breakdown."""
    return (commit_file.additions or 0) + (commit_file.deletions or 0) or 1


def calculate_language_stats(commit_files):
    """Given an iterable of CommitFile rows, return {language: percentage},
    largest share first. Percentages are rounded to 1 decimal place."""
    totals = {}
    for commit_file in commit_files:
        language = detect_language(commit_file.filename)
        if language is None:
            continue
        totals[language] = totals.get(language, 0) + _file_weight(commit_file)

    grand_total = sum(totals.values())
    if not grand_total:
        return {}

    percentages = {
        language: round(weight / grand_total * 100, 1) for language, weight in totals.items()
    }
    return dict(sorted(percentages.items(), key=lambda item: item[1], reverse=True))
