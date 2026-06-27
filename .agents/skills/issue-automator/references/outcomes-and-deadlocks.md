# Outcome Contract and Deadlock Policy

This reference defines the required outcomes and the deadlock policy for issue automation.

## Outcome Contract

Every processed issue must end with exactly one of these outcomes:

1. `DONE`: The issue is already completed and trackers were synced.
2. `IN_REVIEW`: A PR is intentionally handed off for human review and trackers were synced.
3. `SHIPPED`: The code is already on `master` or covered by a merged PR.
4. `SYNCED`: Only tracker synchronization was needed.
5. `LOCAL_DEADLOCK`: The issue is blocked by an issue-specific blocker.
6. `GLOBAL_BLOCKED`: Tooling, auth, repo, CI, or GitHub access prevents safe work.
7. `NEEDS_USER`: Safe progress requires user input.
8. `AMBIGUOUS`: Safe progress requires resolving ambiguity.

`LOCAL_DEADLOCK` and `IN_REVIEW` with no agent writes are both **skip outcomes** — the agent produced no PR or changes for this issue. Both permit advancing to the next oldest issue in a skip loop until a non-skip outcome (`IN_REVIEW` with writes, `DONE`, `SHIPPED`, `SYNCED`, etc.) or no issues remain.

Use `SHIPPED` for direct merges. Use `IN_REVIEW` only when the PR is intentionally paused for human review.

## Deadlock Policy

1. **Local Deadlock Definition**: `LOCAL_DEADLOCK` means the issue is blocked by an issue-specific blocker that does not prevent safe work on a different issue.
2. **Skip Loop Allowance**: Both `LOCAL_DEADLOCK` and `IN_REVIEW` with no agent writes are **skip outcomes** — they do not consume the issue-processing budget. The agent keeps fetching the next oldest issue in a skip loop until a non-skip outcome or no issues remain.
3. **Local Blocker Examples**:
   - Failed checks that do not converge after the retry budget.
   - Preview deploy failures after retry budget.
   - Draft PRs with no safe next action.
   - Repeated implementation failure with no new evidence.
   - Closed unmerged PR where safe progress requires reopening or recreating it.
   - Issue-specific missing requirement that can be documented without blocking all work.
4. **Actionable PR Work vs Blocker**: Unresolved review threads on an `In review` PR are not a local deadlock; treat them as active PR work.
5. **Ambiguity/User Input**: Issue ambiguity that requires user input is `AMBIGUOUS` or `NEEDS_USER`, not `LOCAL_DEADLOCK`.
6. **Global Blockers**: Global blockers prevent safe work in general. Examples:
   - Missing authentication for both CLI and MCP paths.
   - Unavailable GitHub, CI, or repository tooling.
   - Broken local workspace.
   - Missing repository access.
   - Failures that prevent safe work in general.
7. **Resolution**: If a global blocker is encountered, end the run with outcome `GLOBAL_BLOCKED`.
8. **Limits**: Never retry indefinitely. After a non-skip outcome (`IN_REVIEW` with writes, `DONE`, `SHIPPED`, `SYNCED`), stop the run — do not process further issues. `LOCAL_DEADLOCK` and `IN_REVIEW` no-writes loop freely in a skip loop until a non-skip outcome or no issues remain.
