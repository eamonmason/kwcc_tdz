# KWCC Tour de Zwift Results System

A Python-based web application to track KWCC cycling club's internal Tour de Zwift competitions.

## Features

- **Dynamic Event Discovery**: Automatically finds Tour de Zwift events from ZwiftPower API
- **Intelligent Result Fetching**: Fetches race results from ZwiftPower with retry logic
- **Handicap System**: Applies time adjustments based on rider ability groups
- **Race vs Ride Detection**: Configurable handling of race events vs group rides per stage
- **Time Penalties**: Configurable penalties for late-starting events
- **Best Result Selection**: Uses fastest raw time when riders have multiple attempts
- **GC Calculations**: Computes stage results and GC (General Classification) standings
- **Women's GC**: Separate overall classification combining women riders from Groups A and B
- **Static Website**: Generates and hosts results on AWS S3 with CloudFront CDN
- **Automated Updates**: Cron-based hourly updates at :05 past each hour
- **Multi-Year Support**: Handles multiple tour years (e.g., TdZ 2026, TdZ 2027)

### Known Limitations

- **Rider Avatars**: ZwiftPower profile images cannot be automatically downloaded due to access restrictions on their CDN (HTTP 403). The website templates include avatar placeholders that will hide gracefully if images are unavailable.

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

## Result Selection Rules

### Best Result Per Rider

When a rider has multiple results for a stage:

- **Selection Criteria**: Fastest **raw time** from ZwiftPower
- **Penalty Application**: Penalties are added to the fastest raw time
- **Final Time**: Even if penalties make the final time slower than other attempts, the fastest raw time is used

**Example:**
- Attempt 1 (17:10 start): Raw time 45:10, +1 min penalty → Final: 46:10
- Attempt 2 (18:00 start): Raw time 45:30, no penalty → Final: 45:30
- **Result**: Uses 46:10 (fastest raw time with penalty applied)

### Race vs Ride Events

The system distinguishes between race events and group rides:

- **Race Detection**: Uses regex pattern `\brace\b` (case-insensitive) on event names
- **Stage 1**: Race events allowed with 60-second penalty
- **Stages 2-6**: Race events excluded entirely (only group rides count)

### Time Penalties

Stages can have configurable time penalties for events starting at specific times:

- Penalties are defined per stage in the tour configuration
- Applied based on event start timestamp
- Added to raw time before handicap calculation

## GC Rules

- Riders must complete ALL stages to appear in GC standings
- Stage results show all riders who completed that stage
- GC standings only show riders with 100% stage completion

## Women's GC

The system calculates a separate Women's General Classification alongside the standard Group A and Group B standings:

- **Combined Groups**: Women riders from both Group A and Group B compete together in Women's GC
- **Filtering**: Results are filtered by gender (`gender == "F"` in rider data)
- **Same Rules**: Women's GC follows the same completion rules as standard GC (must complete all stages)
- **Display**:
  - Top 10 shown on home page with link to full standings
  - Complete Women's GC standings shown on GC page for each stage
  - Includes guest rider filtering
- **Handicaps**: Women riders maintain their original handicap groups (A1, A2, B3, etc.)

This allows women riders to compete within their own classification while still participating in their assigned group standings.

## System Architecture

### Data Flow

1. **Event Discovery** (automated or manual):
   - Lambda checks S3 for configured event IDs (`config/event_ids.json`)
   - If not found, dynamically discovers events from ZwiftPower API
   - Searches for matching stage events by date and route name

2. **Result Fetching**:
   - Triggered hourly by EventBridge cron schedule (`:05` past each hour)
   - Fetches results for all discovered events
   - Filters to KWCC riders using `config/riders.json`

3. **Result Processing**:
   - Selects best result per rider (fastest raw time)
   - Applies race penalties (if applicable)
   - Applies time penalties (if configured)
   - Applies handicap adjustments
   - Excludes race results (if configured for stage)

4. **Website Generation**:
   - Processor Lambda generates static HTML from results
   - Uploads to S3 website bucket
   - Invalidates CloudFront cache

### Event Discovery

The system can operate in two modes:

1. **Manual Configuration**: Event IDs stored in S3 (`config/event_ids.json`)
2. **Dynamic Discovery**: Automatically searches ZwiftPower API when no IDs configured
   - Searches for "Tour de Zwift" events
   - Filters by stage number and date range
   - Scores candidates based on route name match
   - Returns up to 12 events per stage

### Automation

- **EventBridge Schedule**: `cron(5 * * * ? *)` - runs at :05 past every hour
- **Lambda Functions**:
  - `kwcc-tdz-data-fetcher-prod`: Fetches and processes results
  - `kwcc-tdz-results-processor-prod`: Generates website
- **S3 Buckets**:
  - `kwcc-tdz-2026-data-prod`: Stores results and config
  - `kwcc-tdz-2026-website-prod`: Hosts static website
- **CloudFront**: CDN for website delivery

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
