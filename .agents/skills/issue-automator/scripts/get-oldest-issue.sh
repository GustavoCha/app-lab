#!/usr/bin/env bash
# get-oldest-issue.sh
# Uses the GitHub CLI (gh) to fetch the oldest open issue for the repository.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/gh-auth-utils.sh"

# Ensure gh CLI is installed and authenticated
if ! command -v gh &> /dev/null; then
  echo "Error: 'gh' CLI is not installed or not in PATH." >&2
  exit 127
fi

ensure_gh_auth || exit 1

# Fetch the oldest open issue
issue_json=$(gh issue list --state open --search "is:open is:issue sort:created-asc" --limit 1 --json number,title,createdAt,labels,url 2>/dev/null)

if [ -z "$issue_json" ] || [ "$issue_json" == "[]" ]; then
  echo "No open issues found."
  exit 0
fi

echo "$issue_json"
