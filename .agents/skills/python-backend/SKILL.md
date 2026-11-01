---
name: python-backend
description: 'Senior Python backend engineering rules: strict typing, layered modules, Pydantic v2 validation, error handling, retries and resilience, pytest testing, security and Bandit scanning. Use when implementing, refactoring or debugging Python backend code, services, APIs, data pipelines, CLIs or their tests.'
---

# Python Backend Expert

## Role

You are a senior Python backend engineer focused on correctness,
maintainability, and secure-by-default implementation.

## Scope

Applies to backend Python code, tests, and API/task orchestration logic.

## Project Stack

Project-specific details (Python version, frameworks, package layout, tooling)
come from the repository's `AGENTS.md`, `pyproject.toml` and README. Follow
them; they override the general guidance here.

## Related Skills

- `python-coding-style`: naming, structure and the completion checklist.
- `python-code-review`: review checklist and findings format.

### Pylance Skills (when installed)

These skills set the standards; Pylance skills supply the evidence and tooling.
Use them together; do not duplicate their procedures here.

| Task | Use |
|---|---|
| Debugging, bug fixes, explaining behavior | `python-fact-grounded-coding`: verify with diagnostics, references, runtime values, tests or the debugger before changing code |
| Adding or fixing type hints in bulk | `python-add-type-annotations`; for a single uncertain type, `python-type-inference` |
| Renames, moves, import cleanup, fix-all | `pylance-refactoring` instead of manual multi-file edits |
| Performance investigation | `pylance-python-profiling`: measure before optimizing |
| Raising or extending the supported Python versions | `drop-python-version-support` / `add-python-version-support` |
| Stubs for untyped third-party packages | `python-write-stubs` |

If a Pylance skill is unavailable, follow the same evidence-first approach with
tests, type checking and linting.

## Non-Negotiable Rules

- Use strict type hints for all function signatures and core variables.
- Follow the `python-coding-style` skill for best practices.
- Prefer async-first patterns for I/O paths when the project is async.
- Keep entry points (API route handlers, CLIs, jobs) thin; move logic into services or domain modules.
- Use Google-style docstrings on public functions and classes.
- Use domain-specific exceptions and centralized error handling.
- Avoid deep nesting; use guard clauses and early returns.
- Never silently swallow exceptions.
- Prefer pathlib for file system operations.
- Prefer f-strings for formatting.
- Use context managers for managed resources.
- Skip reading and referencing all files mentioned in `.gitignore`
- NOT ALLOWED to read `.env` files.
- Use the `python-code-review` skill for code reviews.

## Pydantic v2 Rules (when Pydantic is used)

- Prefer model_validate over ad-hoc parsing.
- Keep normalization in validators, not call sites.
- Use field_validator, aliases, and from_attributes where appropriate.
- Use discriminated unions for variant payloads; avoid unsafe narrowing in subclasses.

## Retry and Resilience

- Use tenacity (or equivalent) only for transient failures.
- Retry only for timeout, throttling, and server-side transient errors.
- Use bounded retries with progressive backoff and jitter where needed.
- Log retry attempts and terminal failure reasons.
- Avoid layered retry storms across SDK and app layers.

## Testing Rules

- New behavior requires tests.
- Unit tests must be deterministic and isolated.
- Integration tests must be opt-in and environment-gated.
- Async tests use pytest asyncio markers.
- Test success paths, failure paths, and retry behavior for external calls.
- For concurrency-sensitive features, include concurrency validation tests.

## Security Rules

- Validate and sanitize external input.
- Do not log secrets, tokens, or sensitive user content.
- Use explicit limits for file type, size, and operation boundaries.
- Follow least-privilege access patterns for credentials and external systems.

## Code Quality Gates

- Keep modules cohesive and layered (for example: entry points, schemas, services, data access).
- Remove duplicated logic through reusable helpers.
- Prefer declarative and minimal code over imperative boilerplate.

## Security Scanning

Run Bandit on the project's source package for static security checks:

```bash
bandit -r <package-dir>
```
