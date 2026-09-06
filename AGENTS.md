# AI Agent Guide

This file contains AI-specific guidance only. Human-facing documentation
is kept in the documents linked below.

- README.md

Refer to appropriate documentation as required.

## AI-only rules

- When asked to plan work, create a detailed implementation plan and wait for user review before making code changes.
- If requirements are unclear or missing, ask targeted questions before making assumptions.
- Apply independent software engineering judgement and optimize for long-term code quality. If a request conflicts with good software engineering principles (clarity, maintainability, correctness, performance, security), push back respectfully, explain the tradeoffs, and recommend a better approach. 
- Python tooling is managed with `uv`. Run Python, scripts, and project tools through `uv run` unless there is a clear project-specific reason not to. Use:
  - `uv run ty check` for type checking
  - `uv run ruff check` for linting
  - `uv run pytest` for tests
  - `uv run python` or `uv run path/to/script.py` for Python execution
- After implementing a feature or fixing an issue, consider whether documentation or tests should be added or updated. If so, summarize the recommended changes and ask for user approval before creating or modifying documentation or tests, instead of trying to accomplish everything in one pass.
