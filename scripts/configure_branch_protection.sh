#!/usr/bin/env bash
# Configure branch protection on `main` so a merge is blocked unless every CI
# Validation Gate is green (E12-S4-T3).
#
# This encodes the "merge only with all gates green" policy as GitHub branch
# protection. It is NOT run by CI: applying branch protection is a one-time
# repository-admin action. Run it once (and after adding/removing a required
# check) with a token that has admin rights on the repo:
#
#   GH_REPO=owner/name ./scripts/configure_branch_protection.sh
#
# It requires the `gh` CLI, authenticated as a repo admin.
set -euo pipefail

REPO="${GH_REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
BRANCH="${BRANCH:-main}"

# The required status checks — every Validation Gate that must pass before a PR
# can merge. Keep this list in sync with the CI workflows and CONTRIBUTING.md
# "Validation Gates" section.
REQUIRED_CHECKS=(
  "lint-typecheck"
  "backend-tests"
  "patch-validation"
  "security-baseline"
  "frontend-checks"
  "smoke-e2e"
  "reference-eval-gate"
)

echo "Applying branch protection to ${REPO}@${BRANCH} ..."

checks_json="$(printf '%s\n' "${REQUIRED_CHECKS[@]}" \
  | jq -R . | jq -s '{strict: true, contexts: .}')"

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/${REPO}/branches/${BRANCH}/protection" \
  -f "required_status_checks=${checks_json}" \
  -F "enforce_admins=true" \
  -f "required_pull_request_reviews[required_approving_review_count]=1" \
  -F "restrictions=" \
  1>/dev/null

echo "Done. Required checks on ${BRANCH}:"
printf '  - %s\n' "${REQUIRED_CHECKS[@]}"
