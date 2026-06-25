---
name: repo-opportunity-scout
description: Analyze a repository for product and service opportunities, check existing GitHub issues and pull requests first to avoid duplicates, and create or update GitHub issues for new features and improvements. Use when reviewing a repo for feature gaps, UX friction, reliability or operational problems, or broader product improvements.
---

# Repo Opportunity Scout

## Overview

Use this skill to turn a repository review into concrete, deduplicated GitHub issue proposals. Focus on product value, not just code health.

## Workflow

### 1. Build context

- Read the repo docs and main user flows.
- Identify the product goal, primary users, and any explicit constraints.
- Note architecture, platform, release stage, and roadmap signals.

### 2. Check GitHub first

- Inspect open issues before proposing anything new.
- Inspect open pull requests before proposing anything new.
- If needed, check recently closed issues and PRs for near matches.
- If an open issue already covers the idea, update that issue instead of creating a duplicate.
- If any PR already resolves the idea, skip the proposal and continue.
- If a PR is close but incomplete, comment on it and continue; reopen only when that is the best path.

### 3. Find opportunities

Use `references/opportunity-framework.md` to scan for:

- missing product capabilities
- onboarding or core-workflow friction
- reliability, performance, or cost gaps
- security, privacy, or permissions gaps
- observability, supportability, or maintainability gaps
- automation, integration, retention, or growth opportunities

### 4. Rank proposals

Prefer opportunities with:

- clear user value
- evidence in the repo or product docs
- low ambiguity
- manageable effort
- low dependency risk

### 5. Write GitHub issues

Create one issue per atomic opportunity.
Each issue should include:

- problem statement
- who is affected
- proposed change
- acceptance criteria
- evidence or links
- related issues or PRs
- label suggestions if the repo uses labels

If an existing issue is the right home, update its title or description and add a comment documenting the new angle.

### 6. Report back

Return a compact summary of:

- issues created
- issues updated
- proposals skipped because of overlap
- highest-confidence next steps

## Guardrails

- Do not file speculative issues without repo evidence.
- Do not split a single cohesive improvement into multiple issues.
- Prefer concrete, testable proposals over broad brainstorming.
- Keep issue titles specific and outcome-oriented.
