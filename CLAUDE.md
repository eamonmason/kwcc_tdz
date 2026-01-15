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

## AWS Resources

### eu-west-1 (Primary Region)

- **S3 Buckets**: `kwcc-tdz-2026-data-prod` (data), `kwcc-tdz-2026-website-prod` (static site)
- **Lambda Functions**: `kwcc-tdz-data-fetcher-prod`, `kwcc-tdz-processor-prod`
- **CloudFront**: Distribution `E2M7BDO7EQ2UY6` with custom domain `tdz.kingstonwheelers.cc`
- **Secrets Manager**: ZwiftPower credentials

### us-east-1 (Certificate Region)

- **ACM Certificate**: `tdz.kingstonwheelers.cc` (CloudFront requires certificates in us-east-1)

## Data Flow

1. **EventBridge** triggers `data-fetcher` Lambda hourly at :05 past each hour
2. Lambda checks for event IDs in S3, or dynamically discovers them from ZwiftPower API
3. Lambda fetches results from ZwiftPower API for all discovered events
4. Results processed:
   - Select best result per rider (fastest raw time)
   - Apply race penalties (60s for Stage 1 races, exclude races for Stages 2-6)
   - Apply time penalties (based on event start time)
   - Apply handicap adjustments
5. Stored as JSON in S3 (`results/tdz-2026/stage_X_group_Y.json`)
6. `processor` Lambda generates static HTML from processed results
7. Website uploaded to S3, CloudFront cache invalidated
8. Website accessible at `https://tdz.kingstonwheelers.cc`

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

## Penalty and Result Selection Rules

### Best Result Selection

When riders have multiple results for a stage:

- **Selection Criteria**: Fastest **raw time** from ZwiftPower
- **Penalty Application**: Penalties applied to fastest raw time
- **Final Time**: Used even if penalties make it slower than other attempts

Example: Raw 45:10 (+1 min penalty = 46:10) beats raw 45:30 (no penalty = 45:30)

### Race vs Ride Events

- **Detection**: Regex pattern `\brace\b` (case-insensitive) in event names
- **Stage 1**: Races allowed with +60 second penalty
- **Stages 2-6**: Races excluded entirely (only group rides count)
- Configured per stage in `src/models/tour.py` via `Course.allow_race_events` and `Course.race_event_penalty_seconds`

### Time Penalties

- Configurable per stage via `Course.penalty_events`
- Applied based on event start timestamp
- Added to raw time before handicap calculation
- Example: Monday 17:00 UTC: +1 minute, Monday 18:00 UTC: +1 minute

## S3 Config Files

- `config/riders.json` - Rider registry with handicap groups
- `config/event_ids.json` - ZwiftPower event IDs per stage (optional - system will auto-discover if missing)
- `config/event_timestamps.json` - Event start times for penalty calculation (populated by discovery)

## Manual Result Entry

For riders who haven't opted into ZwiftPower data sharing (at my.zwift.com/profile/connections), results can be added manually.

### S3 Structure

```
s3://kwcc-tdz-2026-data-prod/results/
├── tdz-2026/           # Automatic results from ZwiftPower
│   └── stage_X_group_Y.json
└── manual/             # Manual result overrides
    └── stage_X_group_Y.json
```

### Manual Entry Format

Create a JSON file matching the StageResult model:

```json
[
  {
    "rider_name": "Laura McMullen",
    "rider_id": "12345",
    "stage_number": 1,
    "race_group": "B",
    "handicap_group": "B3",
    "raw_time_seconds": 2850,
    "handicap_seconds": 240,
    "penalty_seconds": 0,
    "penalty_reason": "",
    "raw_position": 1,
    "is_provisional": false,
    "event_id": "manual:strava:123456",
    "timestamp": "2026-01-13T17:00:00Z",
    "guest": false,
    "gender": "F"
  }
]
```

### Adding a Manual Result

```bash
# 1. Create JSON file with result data
# 2. Upload to S3
AWS_PROFILE=personal aws s3 cp /tmp/manual_result.json \
  s3://kwcc-tdz-2026-data-prod/results/manual/stage_1_group_B.json

# 3. Trigger processor to regenerate website
AWS_PROFILE=personal aws lambda invoke --region eu-west-1 \
  --function-name kwcc-tdz-processor-prod --payload '{}' /tmp/output.json
```

Manual results take precedence over automatic results for the same rider_id.

## Dynamic Event Discovery

When `event_ids.json` is empty or missing for a stage:

1. System searches ZwiftPower API for "Tour de Zwift" events
2. Filters by stage number and date range from tour configuration
3. Scores candidates based on:
   - Matching route name (+5 points)
   - Contains "Tour de Zwift" (+2 points)
   - Within stage date range (+3 points)
   - Excludes "run" events and "advanced" variants
4. Returns up to 12 highest-scoring events
5. Fetches event names for race detection

Discovery is fully automated - no manual configuration required for new stages.

## Pre-commit Hooks

Hooks run automatically on commit (lint/format) and push (pytest):

- ruff linting with auto-fix
- ruff formatting
- pytest unit tests (on push only)
- Large file check, YAML validation, trailing whitespace

## Local Development

Local scripts exist for development and testing without AWS:

```bash
# 1. Create .env with ZwiftPower credentials
cp .env.example .env
# Edit .env with your ZWIFTPOWER_USERNAME and ZWIFTPOWER_PASSWORD

# 2. Configure event IDs (one-time setup)
uv run python scripts/fetch_zwiftpower.py --show-config
uv run python scripts/fetch_zwiftpower.py --add-event 1 <EVENT_ID>

# 3. Fetch results from ZwiftPower (caches locally)
uv run python scripts/fetch_zwiftpower.py --stages 1 2 3

# 4. Generate and serve website locally
uv run python scripts/run_local.py
# Opens browser at http://localhost:8000
```

Data is cached in `data/cache/` directory. Use `--force` to refresh cached data.

## Environments

The project supports multiple environments via CDK context:

| Environment | Branch | Domain | Schedule | Secrets |
|-------------|--------|--------|----------|---------|
| `prod` | `main` | `tdz.kingstonwheelers.cc` | Hourly at :05 | Own secret |
| `ci` | `develop` | `ci-tdz.kingstonwheelers.cc` | Manual only | Shares prod |

### CDK Commands for Different Environments

```bash
# Production (default)
AWS_PROFILE=personal cdk synth --all
AWS_PROFILE=personal cdk diff
AWS_PROFILE=personal cdk deploy <StackName>

# CI environment
AWS_PROFILE=personal cdk synth --all --context environment=ci
AWS_PROFILE=personal cdk diff --context environment=ci
AWS_PROFILE=personal cdk deploy <StackName> --context environment=ci
```

### CI Environment Resources

- **S3 Buckets**: `kwcc-tdz-2026-data-ci`, `kwcc-tdz-2026-website-ci`
- **Lambda Functions**: `kwcc-tdz-data-fetcher-ci`, `kwcc-tdz-results-processor-ci`
- **CloudFront**: Distribution `EZQGVFCIAHH7X` with custom domain `ci-tdz.kingstonwheelers.cc`
- **No EventBridge schedule**: Invoke Lambda manually for testing

### Initial CI Setup

After deploying CI for the first time, sync config files from prod:

```bash
AWS_PROFILE=personal aws s3 sync \
  s3://kwcc-tdz-2026-data-prod/config/ \
  s3://kwcc-tdz-2026-data-ci/config/
```

### Manual CI Lambda Invocation

```bash
# Invoke CI data fetcher
AWS_PROFILE=personal aws lambda invoke --region eu-west-1 \
  --function-name kwcc-tdz-data-fetcher-ci --payload '{}' /tmp/ci-output.json

# Invoke CI processor
AWS_PROFILE=personal aws lambda invoke --region eu-west-1 \
  --function-name kwcc-tdz-results-processor-ci --payload '{}' /tmp/ci-output.json
```

## GitHub Actions

Workflow runs on push to `main` or `develop`:

1. **Lint job**: ruff check and format (all branches)
2. **Test job**: pytest with coverage (all branches)
3. **Deploy-prod job**: CDK deploy to production (main branch only)
4. **Deploy-ci job**: CDK deploy to CI environment (develop branch only)

## Important Notes

- Always use `uv run` prefix for Python commands
- AWS profile `personal` for local AWS operations
- CDK uses `uv run python app.py` (configured in `infrastructure/cdk.json`)
- Lambda architecture: x86_64 (not ARM64)
- Region: eu-west-1 (Ireland)
