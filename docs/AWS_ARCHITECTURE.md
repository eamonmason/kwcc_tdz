# KWCC Tour de Zwift 2026 - AWS Architecture

## Overview

This document describes the AWS architecture for the KWCC Tour de Zwift 2026 results tracking system. The system automatically fetches race results from ZwiftPower, applies handicap adjustments, and publishes results to a static website.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GitHub Actions                                  │
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐   │
│  │ Push to main │────▶│ Run Tests    │────▶│ CDK Deploy (all stacks)  │   │
│  └──────────────┘     └──────────────┘     └──────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             AWS (eu-west-1)                                  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ EventBridge (Cron: :05 past every hour)                               │  │
│  └────────────────────────────────┬─────────────────────────────────────┘  │
│                                   │                                         │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Lambda: Data Fetcher                                                  │  │
│  │                                                                        │  │
│  │ • Checks S3 for event IDs, or dynamically discovers from ZwiftPower  │  │
│  │ • Fetches results from ZwiftPower API                                │  │
│  │ • Selects best result per rider (fastest raw time)                   │  │
│  │ • Applies race penalties (Stage 1: +60s, Stages 2-6: exclude races)  │  │
│  │ • Applies time penalties (configurable per stage)                    │  │
│  │ • Applies handicap adjustments                                        │  │
│  │ • Saves processed results to S3                                       │  │
│  │ • On success, triggers Processor Lambda                               │  │
│  └────────────────────────────────┬─────────────────────────────────────┘  │
│                                   │                                         │
│               ┌───────────────────┼───────────────────┐                    │
│               │                   │                   │                    │
│               ▼                   ▼                   ▼                    │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────────────────┐  │
│  │ Secrets Manager│  │ S3: Data       │  │ Lambda: Processor           │  │
│  │                │  │                │  │                             │  │
│  │ ZwiftPower     │  │ • riders.json  │  │ • Generates HTML pages      │  │
│  │ credentials    │  │ • event_ids    │  │ • Uploads to website bucket │  │
│  │                │  │ • stage results│  │ • Invalidates CloudFront    │  │
│  └────────────────┘  └────────────────┘  └──────────────┬──────────────┘  │
│                                                          │                  │
│                                                          ▼                  │
│                              ┌────────────────────────────────────────────┐│
│                              │ S3: Website                                ││
│                              │                                            ││
│                              │ • index.html                               ││
│                              │ • stage_X.html                             ││
│                              │ • gc.html                                  ││
│                              │ • css/styles.css                           ││
│                              └────────────────────────────┬───────────────┘│
│                                                           │                 │
│                                                           ▼                 │
│                              ┌────────────────────────────────────────────┐│
│                              │ CloudFront Distribution                    ││
│                              │                                            ││
│                              │ • HTTPS enforcement                        ││
│                              │ • Global edge caching                      ││
│                              │ • Auto-invalidation on updates            ││
│                              └────────────────────────────────────────────┘│
│                                                           │                 │
└───────────────────────────────────────────────────────────┼─────────────────┘
                                                            │
                                                            ▼
                                                     ┌──────────────┐
                                                     │   Website    │
                                                     │   Visitors   │
                                                     └──────────────┘
```

## AWS Resources

### DataStack

| Resource | Name | Purpose |
|----------|------|---------|
| S3 Bucket | `kwcc-tdz-2026-data-prod` | Stores configuration and processed results |
| S3 Bucket | `kwcc-tdz-2026-website-prod` | Hosts static website files |
| Secrets Manager | `kwcc-tdz/zwiftpower-credentials-prod` | ZwiftPower authentication |

### ComputeStack

| Resource | Name | Purpose |
|----------|------|---------|
| Lambda | `kwcc-tdz-data-fetcher-prod` | Fetches ZwiftPower results |
| Lambda | `kwcc-tdz-results-processor-prod` | Generates website |
| Lambda Layer | Dependencies | Python packages for Lambdas |
| EventBridge Rule | `kwcc-tdz-hourly-fetch-prod` | Hourly trigger |
| SNS Topic | `kwcc-tdz-alerts-prod` | Error notifications |
| CloudWatch Alarms | Various | Monitor Lambda errors/throttles |

### CdnStack

| Resource | Name | Purpose |
|----------|------|---------|
| CloudFront | Distribution | CDN for website |
| OAI | Origin Access Identity | Secure S3 access |

## Data Flow

1. **Hourly Trigger**: EventBridge triggers Data Fetcher Lambda at :05 past each hour
2. **Event Discovery**:
   - Lambda checks S3 for event IDs (`config/event_ids.json`)
   - If empty/missing, dynamically discovers events from ZwiftPower API
   - Searches for "Tour de Zwift" events matching stage number and date range
   - Scores candidates and selects up to 12 events per stage
3. **Data Fetch**: Lambda fetches results from ZwiftPower using OAuth
4. **Result Selection**: Selects best result per rider based on fastest raw time
5. **Processing**:
   - Apply race penalties (Stage 1: +60s, Stages 2-6: exclude races)
   - Apply time penalties (based on event start time)
   - Apply handicap adjustments (based on rider group)
6. **Storage**: Processed results saved to S3 data bucket
7. **Website Generation**: Processor Lambda generates HTML from results
8. **Upload**: HTML uploaded to S3 website bucket
9. **Cache Invalidation**: CloudFront cache invalidated
10. **Serving**: CloudFront serves content to users

## Configuration Files in S3

```
s3://kwcc-tdz-2026-data-prod/
├── config/
│   ├── riders.json             # Rider registry with ZwiftPower IDs (required)
│   ├── event_ids.json          # Stage event ID mappings (optional, auto-discovered)
│   └── event_timestamps.json   # Event start times (populated by discovery)
└── results/
    └── tdz-2026/
        ├── stage_1_group_A.json
        ├── stage_1_group_B.json
        ├── stage_2_group_A.json
        └── ...
```

**Note**: The `event_ids.json` file is optional. If empty or missing for a stage, the system will automatically discover events from ZwiftPower API. This makes the system fully autonomous for new stages.

## Monitoring

- **CloudWatch Logs**: All Lambda invocations logged
- **CloudWatch Alarms**:
  - Data Fetcher errors
  - Data Fetcher throttles
  - Processor errors
- **SNS Notifications**: Subscribe email to `kwcc-tdz-alerts-prod` topic

## Deployment

### Prerequisites

1. AWS CLI configured with credentials
2. AWS CDK installed (`npm install -g aws-cdk`)
3. Python with uv
4. Docker (for Lambda layer bundling)

### First-Time Setup

```bash
# Bootstrap CDK (one-time per account/region)
cd infrastructure
cdk bootstrap aws://ACCOUNT_ID/eu-west-1

# Deploy all stacks
cdk deploy --all
```

### Configure Secrets

After deployment, update the ZwiftPower credentials:

```bash
aws secretsmanager put-secret-value \
  --secret-id kwcc-tdz/zwiftpower-credentials-prod \
  --secret-string '{"username":"your@email.com","password":"your-password"}'
```

### Upload Configuration

Upload rider registry and event IDs to S3:

```bash
# Upload riders
aws s3 cp data/riders.json s3://kwcc-tdz-2026-data-prod/config/riders.json

# Upload event IDs (if known)
aws s3 cp data/event_ids.json s3://kwcc-tdz-2026-data-prod/config/event_ids.json
```

### GitHub Actions Setup

Set the following secrets in your GitHub repository:

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | AWS access key with CDK deploy permissions |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |

### Manual Invocation

To manually trigger a data fetch:

```bash
aws lambda invoke \
  --function-name kwcc-tdz-data-fetcher-prod \
  --payload '{}' \
  /dev/stdout
```

To manually trigger website generation:

```bash
aws lambda invoke \
  --function-name kwcc-tdz-results-processor-prod \
  --payload '{}' \
  /dev/stdout
```

## Local Development vs AWS

| Aspect | Local | AWS |
|--------|-------|-----|
| Data Storage | `data/` directory | S3 buckets |
| Configuration | `data/riders.json` | S3 `config/riders.json` |
| Event IDs | `data/event_ids.json` | S3 `config/event_ids.json` |
| Credentials | Environment variables | Secrets Manager |
| Website Output | `output/` directory | S3 website bucket |
| Scheduling | Manual | EventBridge hourly |
| CDN | Python HTTP server | CloudFront |

## Migration from Local to AWS

1. **Deploy Infrastructure**
   ```bash
   cd infrastructure && cdk deploy --all
   ```

2. **Configure Credentials**
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id kwcc-tdz/zwiftpower-credentials-prod \
     --secret-string '{"username":"...","password":"..."}'
   ```

3. **Upload Rider Registry**
   ```bash
   python -c "
   from src.config import load_riders_from_csv
   import json
   registry = load_riders_from_csv()
   with open('data/riders.json', 'w') as f:
       json.dump(registry.model_dump(), f, indent=2)
   "
   aws s3 cp data/riders.json s3://kwcc-tdz-2026-data-prod/config/riders.json
   ```

4. **Upload Event IDs** (once discovered)
   ```bash
   aws s3 cp data/event_ids.json s3://kwcc-tdz-2026-data-prod/config/event_ids.json
   ```

5. **Verify**
   - Check CloudWatch logs for Lambda execution
   - Access website via CloudFront URL (from CDK output)

## Security

- All S3 buckets are private (no public access)
- CloudFront uses Origin Access Identity (OAI)
- Secrets stored in AWS Secrets Manager
- IAM roles follow least privilege principle
- HTTPS enforced via CloudFront

## Cost Estimate

| Service | Estimated Monthly Cost |
|---------|----------------------|
| Lambda | ~$0.50 (hourly invocations) |
| S3 | ~$0.10 (minimal storage) |
| CloudFront | ~$1.00 (low traffic) |
| Secrets Manager | ~$0.40 (1 secret) |
| **Total** | **~$2/month** |
