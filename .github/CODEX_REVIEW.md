# Codex PR Review Flow

This repository uses a lightweight OpenClaw-style PR status system so reviewers can scan the current state from labels instead of reading the whole timeline first.

## Default Flow

1. Open a focused PR with a clear title: `type(scope): concise change`.
2. Add behavior proof for user-visible changes: tests, screenshots, videos, logs, curl output, or before/after notes.
3. Let automatic Codex review run. The repository is configured for review on PR creation and again after pushes.
4. When a review looks stale, comment `@codex review` on the PR.
5. Treat the Codex `eyes` reaction as acknowledgement, then wait for the actual review comment or thumbs-up.
6. Classify the PR from the newest bot comments, review threads, and evidence. Do not trust stale labels alone.

## Status Labels

- `codex:needs-review`: current PR head still needs Codex review.
- `codex:review-requested`: Codex review was requested or should be running automatically.
- `codex:reviewed`: Codex posted a result after the latest request.
- `codex:needs-rerun`: new commits or stale results require another review.
- `codex:setup-issue`: Codex could not run because of account, connector, environment, or repo setup.
- `status: 🔁 re-review loop`: a fresh review is in progress or expected.
- `status: 🛠️ actively grinding`: author is still iterating.
- `status: 📣 needs proof`: reviewers need better behavior proof.
- `status: 👀 ready for maintainer look`: no automation blocker is known; maintainer should inspect.
- `status: ⏳ waiting on author`: author action or clarification is needed.
- `status: ✅ merge-ready`: evidence and review are clear; normal merge gates may proceed.
- `status: 🚧 blocked`: blocked by setup, missing input, failing proof, or a decision.

## Proof Labels

Use proof labels for behavior changes, especially external or UI-facing fixes.

- `proof: missing`
- `proof: supplied`
- `proof: sufficient`
- `proof: 📸 screenshot`
- `proof: 🎥 video`

## Risk Labels

Use merge-risk labels when the blast radius matters:

- `merge-risk: 🚨 automation`
- `merge-risk: 🚨 compatibility`
- `merge-risk: 🚨 data-loss`
- `merge-risk: 🚨 security-boundary`
- `merge-risk: 🚨 other`

## Automation Notes

The `PR status labels` workflow only calls GitHub's API to add or remove labels. It does not check out PR code and does not execute contributor code.
