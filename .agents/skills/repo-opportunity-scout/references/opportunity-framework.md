# Opportunity Framework

## Scan Areas

- user onboarding and first-run friction
- core workflow gaps
- discoverability and UX clarity
- reliability and failure recovery
- performance, latency, and cost
- security, privacy, and permissions
- observability, supportability, and diagnostics
- maintainability and developer experience
- integrations and automation
- accessibility and localization
- retention, growth, and monetization loops

## Evidence To Collect

- repo docs and roadmap notes
- issue and PR history
- product copy and user-facing flows
- code paths that handle errors, edge cases, or hot paths
- tests that reveal missing behavior
- config, telemetry, or deployment gaps

## Prioritization

- P0: blocks users, data loss, security, or severe reliability issues
- P1: major UX, revenue, or operational impact
- P2: meaningful improvement with moderate effort
- P3: nice-to-have or exploratory

Score each idea using:

- impact
- reach
- confidence
- effort
- risk

## Duplicate Rules

- If an open issue already covers the idea, update it instead of opening another issue.
- If any PR already addresses the idea, skip the proposal.
- If a PR is close but incomplete, comment on it and continue; reopen only if that is the best route.
- Merge overlapping ideas into one issue when they target the same user outcome.

## Issue Shape

- Title: verb-first or outcome-first, specific, non-generic.
- Body:
  - problem
  - why it matters
  - proposed change
  - acceptance criteria
  - evidence
  - related issues or PRs
  - risks or dependencies
