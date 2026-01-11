# KWCC Tour de Zwift Results System

A Python-based web application to track KWCC cycling club's internal Tour de Zwift competitions.

## Features

- Fetches race results from ZwiftPower
- Applies handicap time adjustments based on rider ability groups
- Calculates stage results and GC (General Classification) standings
- Generates a static website hosted on AWS S3 with CloudFront CDN
- Automatic hourly updates during active stages
- Support for multiple tour years (e.g., TdZ 2026, TdZ 2027)

## Handicap System

### Group A

| Group | Handicap |
|-------|----------|
| A1    | +10 min  |
| A2    | +5 min   |
| A3    | scratch  |

### Group B

| Group | Handicap |
|-------|----------|
| B1    | +15 min  |
| B2    | +10 min  |
| B3    | +4 min   |
| B4    | scratch  |

## GC Rules

- Riders must complete ALL stages to appear in GC standings
- Stage results show all riders who completed that stage
- GC standings only show riders with 100% stage completion

## Development

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- AWS CLI configured with appropriate credentials

### Setup

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run linting
uv run ruff check .
```

### Project Structure

```
kwcc_tdz/
├── src/
│   ├── models/         # Pydantic data models
│   ├── config/         # Configuration and loaders
│   ├── fetcher/        # ZwiftPower integration
│   ├── processor/      # Business logic
│   ├── generator/      # Website generation
│   └── lambda_handlers/ # AWS Lambda entry points
├── infrastructure/     # AWS CDK stacks
├── tests/              # Test suite
└── static/             # CSS/JS assets
```

## Deployment

The system is deployed automatically via GitHub Actions on push to main:

1. Linting and tests run
2. CDK deploys infrastructure changes
3. Lambda functions are updated
4. CloudFront cache is invalidated

## License

Private - KWCC Internal Use Only
