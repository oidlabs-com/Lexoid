---
name: python-coding-style
description: 'Python coding style and quality standards: immutability, KISS/DRY/YAGNI, file and function size limits, error handling, input validation, naming conventions, code smells, unit tests and a completion checklist. Use when writing, refactoring or finishing Python code, adding tests, or checking code quality before marking work complete.'
---

# Coding Style

## Immutability (CRITICAL)

ALWAYS create new objects, NEVER mutate existing ones:

```
# Pseudocode
WRONG:  modify(original, field, value) → changes original in-place
CORRECT: update(original, field, value) → returns new copy with change
```

Rationale: Immutable data prevents hidden side effects, makes debugging easier, and enables safe concurrency.

## Core Principles

### KISS (Keep It Simple)

- Prefer the simplest solution that actually works
- Avoid premature optimization
- Optimize for clarity over cleverness

### DRY (Don't Repeat Yourself)

- Extract repeated logic into shared functions or utilities
- Avoid copy-paste implementation drift
- Introduce abstractions when repetition is real, not speculative

### YAGNI (You Aren't Gonna Need It)

- Do not build features or abstractions before they are needed
- Avoid speculative generality
- Start simple, then refactor when the pressure is real

## File Organization

MANY SMALL FILES > FEW LARGE FILES:

- High cohesion, low coupling
- 200-400 lines typical, 800 max
- Extract utilities from large modules
- Organize by feature/domain, not by type

## Error Handling

ALWAYS handle errors comprehensively:

- Handle errors explicitly at every level
- Provide user-friendly error messages in UI-facing code
- Log detailed error context on the server side
- Never silently swallow errors

## Input Validation

ALWAYS validate at system boundaries:

- Validate all user input before processing
- Use schema-based validation where available
- Fail fast with clear error messages
- Never trust external data (API responses, user input, file content)

## Naming Conventions

Follow [PEP 8](https://peps.python.org/pep-0008/#naming-conventions). Do not use `camelCase`, except where an external API requires it (for example, overriding `unittest.TestCase.setUp`).

| Kind | Style | Example |
| --- | --- | --- |
| Variables, functions, methods, parameters | `snake_case` | `user_count`, `load_config()` |
| Modules | short `snake_case` | `user_service.py` |
| Packages | short lowercase, no underscores if possible | `billing`, `utils` |
| Classes, Pydantic models, dataclasses, `Protocol`, `TypedDict`, `Enum` | `PascalCase` (CapWords) | `UserProfile`, `AppConfig` |
| Exceptions | `PascalCase` ending in `Error` | `ValidationError`, `NotFoundError` |
| Type variables / aliases | short `PascalCase` | `T`, `ModelT`, `JsonDict` |
| Constants (module level) and `Enum` members | `UPPER_SNAKE_CASE` | `MAX_RETRIES`, `Status.ACTIVE` |
| Internal / non-public names | leading underscore | `_parse_row`, `_cache` |
| Name clashes with keywords or builtins | trailing underscore | `class_`, `type_` |

- Booleans: prefer `is_`, `has_`, `should_` or `can_` prefixes (`is_valid`, `has_access`).
- Use descriptive names; single letters only for short loops, indices or math (`i`, `x`).
- Keep acronyms uppercase in class names (`HTTPClient`, `JSONParser`) and lowercase in snake_case names (`http_client`, `json_path`).
- Do not shadow builtins (`id`, `type`, `list`, `input`) with local names.
- Reserve double leading underscores (`__name`) for deliberate name mangling; never invent `__dunder__` names.

## Code Smells to Avoid

### Deep Nesting

Prefer early returns over nested conditionals once the logic starts stacking.

### Magic Numbers

Use named constants for meaningful thresholds, delays, and limits.

### Long Functions

Split large functions into focused pieces with clear responsibilities.

### Tests

- For every major functional change, add a unit test that validates it.
- Before writing a new test, check the project's test directory (for example, `tests/`) for a matching test file. If none clearly fits, create one.

## Code Quality Checklist

Before marking work complete:

- [ ] Code is readable and well-named
- [ ] Functions are small (<50 lines)
- [ ] Files are focused (<800 lines)
- [ ] No deep nesting (>4 levels)
- [ ] Proper error handling
- [ ] No hardcoded values (use constants or config)
- [ ] No mutation (immutable patterns used)
- [ ] No new type-checker or linter diagnostics in changed files
- [ ] Relevant tests run and pass

## Tooling (when Pylance skills are installed)

This skill defines the standard; use Pylance skills to apply and check it:

- `pylance-refactoring`: renames to fix naming, unused-import cleanup and import
  style changes across files.
- `python-add-type-annotations` / `python-type-inference`: add or correct type
  hints with verified types.
- `python-fact-grounded-coding`: confirm behavior and diagnostics before and
  after changes.
