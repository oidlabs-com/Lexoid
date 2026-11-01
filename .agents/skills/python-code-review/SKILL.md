---
name: python-code-review
description: 'Python code review checklist and severity-ranked findings format covering design and architecture, code quality, typing, error handling, input validation, security, performance and test coverage. Use when reviewing a PR, diff, branch or changed files, auditing code quality, or looking for bugs, design flaws, security vulnerabilities and missing tests.'
---

# Code Review

Mode: PR review, code analysis
Focus: Quality, security, maintainability, design flaws, architectural integrity

## Behavior

- Read thoroughly before commenting
- Critically evaluate whether coding and design best practices were followed
- Prioritize issues by severity (critical > high > medium > low)
- Suggest concrete fixes and code examples, don't just point out problems
- Check for security vulnerabilities, race conditions, and error paths
- Consider performance, maintainability, and operational complexity

## Verify Before Reporting

A finding is a hypothesis until checked. When the Pylance skills are installed:

- Use `python-fact-grounded-coding` to confirm a suspected bug with diagnostics,
  references, call sites, a focused snippet or a test before reporting it as fact.
- Use `python-type-inference` when a finding depends on what type a symbol
  actually has.
- Recommend `pylance-refactoring` for mechanical fixes (renames, unused imports,
  import style) rather than hand-written multi-file edits.

Label anything you could not verify as unverified, with what would confirm it.
Apply the `python-coding-style` skill as the style baseline.

## Review Checklist

### 1. Design & Architecture

- [ ] **Single Responsibility (SRP):** Each class, module, and function has one clear, well-defined purpose
- [ ] **Layering & Separation of Concerns:** API handlers remain thin; business logic resides in services; data access is decoupled
- [ ] **Coupling & Cohesion:** High cohesion within modules, loose coupling between modules; avoids leaky abstractions
- [ ] **Simplicity (KISS & YAGNI):** Minimal viable abstraction; no premature over-engineering or speculative generality
- [ ] **Extensibility & Contracts:** Clean, stable public interfaces; composable helpers rather than bloated conditional trees

### 2. Code Quality & Craftsmanship

- [ ] **Immutability & State Management:** Prefers immutable data flow; no unexpected mutations or hidden side effects
- [ ] **Control Flow & Nesting:** Uses guard clauses and early returns; avoids deep nesting (>3–4 levels)
- [ ] **Function & File Size:** Functions are focused (<50 lines); files remain modular (<400–800 lines)
- [ ] **Typing & Strictness:** Strict type hints on public APIs, function signatures, and core data models
- [ ] **Naming & Readability:** Descriptive, intention-revealing names; boolean flags use prefixes (`is_`, `has_`, `should_`)
- [ ] **DRY (Don't Repeat Yourself):** Reusable logic extracted into helpers without copy-paste drift

### 3. Reliability & Error Handling

- [ ] **Input Validation:** External input sanitized and validated at boundaries (e.g., Pydantic models)
- [ ] **Error Handling:** Domain-specific exceptions; explicit failure handling; no silently swallowed exceptions
- [ ] **Resilience & Timeouts:** Transient network operations use bounded retries, backoff, and explicit timeouts
- [ ] **Edge Cases & Concurrency:** Handles empty inputs, nulls, boundary values, async race conditions, and resource cleanup (context managers)

### 4. Security & Performance

- [ ] **Security:** Injection prevention (SQL, command, prompt), authentication/authorization checks, no exposed secrets/tokens
- [ ] **Performance:** No accidental $O(N^2)$ loops, unnecessary I/O, unindexed queries, or memory bloat

### 5. Test Coverage & Verifiability

- [ ] **Test Coverage:** Unit tests exist for new behavior, edge cases, and failure modes
- [ ] **Test Isolation & Integrity:** Tests are isolated and deterministic; avoids tautological mocks that mask real behavior

## Output Format

Group findings by file, severity first (Critical > High > Medium > Low).
For each issue:

- **Location:** file:line
- **Issue:** Concise description of the design flaw, bug, or code smell
- **Impact:** Why it matters (maintainability, reliability, security, performance)
- **Fix:** Concrete recommendation or code snippet
