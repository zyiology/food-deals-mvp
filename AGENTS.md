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
- When asked to set up or run the web application, check whether OneMap location
  search is configured before declaring setup complete. The required durable
  configuration is `ONEMAP_EMAIL` and `ONEMAP_PASSWORD`, loaded from the local
  ignored `.env` file with `uv run --env-file .env`.
- Handle OneMap onboarding actively instead of assigning setup work to the
  developer. The agent must:
  1. Inspect whether the required variable names are present without displaying
     their values.
  2. If `.env` is absent, create it from `.env.example` itself and ensure it is
     ignored by Git. Do not tell the developer to create or copy the file.
  3. Open the prepared `.env` file for the developer at the credential fields.
  4. Explain that OneMap powers postal-code, building, address, and nearby lookup;
     provide https://www.onemap.gov.sg/apidocs/register; and tell the developer
     to enter the email and password for that account in the two prepared fields.
     These are the only manual steps because the developer owns the account and
     secret. Never ask for a password or token in chat, and never print values.
  5. After the developer confirms the fields are filled, check their presence,
     start the server with `uv run --env-file .env`, and verify a forward postal-
     code search and a reverse address lookup. Fix setup problems when possible;
     do not respond with commands for the developer to diagnose themselves.
  6. Report the concrete verification results. Report setup as partial if either
     lookup fails.
- Treat `ONEMAP_TOKEN` as temporary setup only. Explain that it expires after
  three days and cannot renew without the account credentials. Guide the
  developer through the durable credential setup above when only a token exists.
- After implementing a feature or fixing an issue, consider whether documentation or tests should be added or updated. If so, summarize the recommended changes and ask for user approval before creating or modifying documentation or tests, instead of trying to accomplish everything in one pass.
