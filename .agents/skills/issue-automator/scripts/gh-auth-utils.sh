#!/usr/bin/env bash
# gh-auth-utils.sh
# Ensures gh CLI is authenticated. Uses the current logged-in user when possible;
# tries other logged-in users if auth fails. Does NOT hardcode any user.
#
# Usage:
#   source "$(dirname "$0")/gh-auth-utils.sh"
#   ensure_gh_auth

# Ensures gh CLI auth is working. If the current user fails, tries other
# logged-in users until one works. Returns 0 on success, 1 if no user works.
ensure_gh_auth() {
  if ! command -v gh &> /dev/null; then
    echo "Error: 'gh' CLI is not installed or not in PATH." >&2
    return 1
  fi

  # Check if current auth works
  if gh auth status &> /dev/null; then
    return 0
  fi

  # Current user failed. Find other logged-in users from gh config.
  # gh config list outputs lines like `github.com:user:some-user` or
  # `github.com:git_protocol:https`. Extract user entries.
  local users
  users=$(gh config list 2>/dev/null | grep -oP '^github\.com:user:\K.+$' || true)

  if [ -z "$users" ]; then
    # Fallback: try parsing gh auth status output
    users=$(gh auth status 2>&1 | grep -oP 'as \K\S+' || true)
  fi

  if [ -n "$users" ]; then
    local tried=""
    while IFS= read -r user; do
      user="${user#"${user%%[![:space:]]*}"}"  # trim leading
      user="${user%"${user##*[![:space:]]}"}"  # trim trailing
      [ -z "$user" ] && continue
      # Skip if already tried
      if echo "$tried" | grep -qF "$user"; then
        continue
      fi
      tried="$tried $user"

      if gh auth switch --user "$user" 2>/dev/null; then
        echo "Switched gh auth to $user" >&2
        return 0
      fi
    done <<< "$users"
  fi

  echo "Error: gh CLI not authenticated as any user. Run 'gh auth login' first." >&2
  return 1
}
