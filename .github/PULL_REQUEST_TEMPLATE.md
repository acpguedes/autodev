# Pull Request

## Summary

<!-- What does this PR deliver? One or two sentences. -->

## Scope

- **Epic / Story:** <!-- e.g. E3 (epic PR) or E3-S1 (story), or n/a for fixes/docs -->
- **Type:** <!-- feature / fix / refactor / docs / chore -->
- **Related issues:** <!-- #123, closes #456 -->

## Changes

<!-- Bullet list of the concrete changes. Keep it reviewable. -->

-

## Testing

<!-- Which tests were run and why that scope is sufficient.
     Story branches: story-scoped tests. Epic → main: FULL suite required. -->

- [ ] Story-scoped tests pass (`pytest <paths> -q`)
- [ ] Full suite green — **required for epic → `main` PRs** (`make check` or `make container-check`)
- [ ] No unnecessary tests added (each new test protects a delivered behavior)

## Quality checklist

- [ ] All new/changed packages, classes, methods, and functions have English
      docstrings (description, args, returns, raises)
- [ ] All new/changed signatures have complete type hints; `make typecheck` passes
- [ ] Lint passes (`make lint`)
- [ ] No secrets, credentials, or `.env` content in the diff
- [ ] Documentation updated (`docs/`, and `docs/v2_platform/progress.md` +
      the epic phase doc for story/epic state changes)
- [ ] ADR/RFC added or referenced if a public contract changed
      (`docs/v2_platform/decisions/`)
- [ ] Contract tests green for any touched extension point

## Notes for reviewers

<!-- Anything that needs special attention: migrations, breaking changes, follow-ups. -->
