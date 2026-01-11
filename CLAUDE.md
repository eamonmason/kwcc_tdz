# CLAUDE.md - Project Instructions for Claude

## Project Overview

KWCC Tour de Zwift 2026 Results System - A Python application that tracks cycling club competition results from ZwiftPower, applies handicap adjustments, and publishes standings to a static website on AWS.

## Tech Stack

- **Language**: Python 3.12
- **Package Manager**: uv (use `uv run` for all Python commands)
- **Linting**: ruff
- **Testing**: pytest
- **Infrastructure**: AWS CDK (Python)
- **CI/CD**: GitHub Actions with OIDC authentication

## Key Commands

```bash
# Install dependencies
uv sync --extra dev          # Development dependencies
uv sync --extra cdk          # CDK dependencies
uv sync --extra dev --extra cdk  # Both

# Linting and formatting
uv run ruff check .          # Run linter
uv run ruff check --fix .    # Auto-fix lint issues
uv run ruff format .         # Format code

# Testing
uv run pytest tests/unit/ -v # Run unit tests

# Pre-commit hooks (installed automatically)
uv run pre-commit run --all-files  # Run all hooks manually

# CDK commands (from infrastructure/ directory)
AWS_PROFILE=personal cdk list
AWS_PROFILE=personal cdk synth --all
AWS_PROFILE=personal cdk deploy <StackName> --require-approval never

# AWS Lambda invocation
AWS_PROFILE=personal aws lambda invoke --region eu-west-1 --function-name kwcc-tdz-data-fetcher-prod --payload '{}' /tmp/output.json
```

## Project Structure

```
kwcc_tdz/
├── src/
│   ├── config/          # Tour config, rider loader
│   ├── fetcher/         # ZwiftPower API client
│   ├── generator/       # Jinja2 website generation
│   ├── lambda_handlers/ # AWS Lambda entry points
│   ├── models/          # Pydantic data models
│   └── processor/       # Handicap/penalty calculation
├── infrastructure/      # AWS CDK stacks
│   ├── app.py          # CDK app entry point
│   └── stacks/         # DataStack, ComputeStack, GitHubActionsStack
├── static/             # CSS/JS assets
├── tests/unit/         # Unit tests
└── .github/workflows/  # GitHub Actions
```

## AWS Resources (eu-west-1)

- **S3 Buckets**: `kwcc-tdz-2026-data-prod` (data), `kwcc-tdz-2026-website-prod` (static site)
- **Lambda Functions**: `kwcc-tdz-data-fetcher-prod`, `kwcc-tdz-processor-prod`
- **CloudFront**: Distribution for website CDN
- **Secrets Manager**: ZwiftPower credentials

## Data Flow

1. **EventBridge** triggers `data-fetcher` Lambda hourly
2. Lambda fetches results from ZwiftPower API
3. Results processed with handicaps and penalties
4. Stored as JSON in S3 (`results/tdz-2026/stage_X_group_Y.json`)
5. `processor` Lambda generates static HTML
6. Website uploaded to S3, CloudFront cache invalidated

## Handicap System

| Group | Handicap Added |
|-------|----------------|
| A1    | +10 minutes    |
| A2    | +5 minutes     |
| A3    | +0 minutes     |
| B1    | +15 minutes    |
| B2    | +10 minutes    |
| B3    | +4 minutes     |
| B4    | +0 minutes     |

## Penalty System

- Monday 17:00 UTC (5pm): +1 minute penalty
- Monday 18:00 UTC (6pm): +1 minute penalty
- Penalties configured in `src/models/penalty.py`

## S3 Config Files

- `config/riders.json` - Rider registry with handicap groups
- `config/event_ids.json` - ZwiftPower event IDs per stage
- `config/event_timestamps.json` - Event start times for penalty calculation

## Pre-commit Hooks

Hooks run automatically on commit (lint/format) and push (pytest):

- ruff linting with auto-fix
- ruff formatting
- pytest unit tests (on push only)
- Large file check, YAML validation, trailing whitespace

## GitHub Actions

Workflow runs on push to main:

1. **Lint job**: ruff check and format
2. **Test job**: pytest with coverage
3. **Deploy job**: CDK deploy (OIDC auth, no secrets needed)

## Important Notes

- Always use `uv run` prefix for Python commands
- AWS profile `personal` for local AWS operations
- CDK uses `uv run python app.py` (configured in `infrastructure/cdk.json`)
- Lambda architecture: x86_64 (not ARM64)
- Region: eu-west-1 (Ireland)
