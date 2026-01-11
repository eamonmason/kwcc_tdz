#!/usr/bin/env python3
"""Script to set up AWS resources with initial configuration."""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Default values
DATA_BUCKET = "kwcc-tdz-2026-data-prod"
SECRET_NAME = "kwcc-tdz/zwiftpower-credentials-prod"
REGION = "eu-west-1"


def run_command(cmd: list[str], capture: bool = False) -> str | None:
    """Run a shell command."""
    logger.debug(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        if capture:
            logger.error(f"Command failed: {result.stderr}")
        return None
    return result.stdout.strip() if capture else None


def upload_riders(bucket: str):
    """Convert CSV riders to JSON and upload to S3."""
    from src.config import load_riders_from_csv

    csv_path = Path("KW TDZ sign on 2026 - Sheet1.csv")
    if not csv_path.exists():
        csv_path = Path("data/riders.csv")
    if not csv_path.exists():
        logger.error("Cannot find riders CSV file")
        return False

    logger.info(f"Loading riders from {csv_path}...")
    registry = load_riders_from_csv(csv_path)

    # Save to local JSON
    local_path = Path("data/riders.json")
    local_path.parent.mkdir(exist_ok=True)

    with local_path.open("w") as f:
        json.dump(registry.model_dump(), f, indent=2, default=str)
    logger.info(f"Saved {len(registry.riders)} riders to {local_path}")

    # Upload to S3
    s3_path = f"s3://{bucket}/config/riders.json"
    result = run_command(
        ["aws", "s3", "cp", str(local_path), s3_path, "--region", REGION],
        capture=True,
    )
    if result is not None:
        logger.info(f"Uploaded riders to {s3_path}")
    else:
        logger.error("Failed to upload riders to S3")
        return False
    return True


def upload_event_ids(bucket: str, event_ids_file: Path):
    """Upload event IDs to S3."""
    if not event_ids_file.exists():
        logger.warning(f"Event IDs file not found: {event_ids_file}")
        return False

    s3_path = f"s3://{bucket}/config/event_ids.json"
    result = run_command(
        ["aws", "s3", "cp", str(event_ids_file), s3_path, "--region", REGION],
        capture=True,
    )
    if result is not None:
        logger.info(f"Uploaded event IDs to {s3_path}")
        return True
    else:
        logger.error("Failed to upload event IDs to S3")
        return False


def configure_secret(secret_name: str, username: str, password: str):
    """Configure ZwiftPower credentials in Secrets Manager."""
    secret_value = json.dumps({"username": username, "password": password})

    result = run_command(
        [
            "aws",
            "secretsmanager",
            "put-secret-value",
            "--secret-id",
            secret_name,
            "--secret-string",
            secret_value,
            "--region",
            REGION,
        ],
        capture=True,
    )
    if result is not None:
        logger.info(f"Configured credentials in {secret_name}")
        return True
    else:
        logger.error("Failed to configure credentials")
        return False


def trigger_lambda(function_name: str):
    """Manually trigger a Lambda function."""
    logger.info(f"Triggering Lambda: {function_name}")
    result = run_command(
        [
            "aws",
            "lambda",
            "invoke",
            "--function-name",
            function_name,
            "--payload",
            "{}",
            "--region",
            REGION,
            "/dev/stdout",
        ],
        capture=True,
    )
    if result:
        logger.info(f"Lambda response: {result}")
        return True
    return False


def get_website_url() -> str | None:
    """Get the CloudFront website URL."""
    result = run_command(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            "KwccTdzProdCdnStack",
            "--query",
            "Stacks[0].Outputs[?OutputKey=='WebsiteUrl'].OutputValue",
            "--output",
            "text",
            "--region",
            REGION,
        ],
        capture=True,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="Set up AWS resources for KWCC TdZ")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # upload-riders command
    upload_riders_parser = subparsers.add_parser(
        "upload-riders", help="Upload rider registry to S3"
    )
    upload_riders_parser.add_argument("--bucket", default=DATA_BUCKET, help="S3 bucket")

    # upload-events command
    upload_events_parser = subparsers.add_parser(
        "upload-events", help="Upload event IDs to S3"
    )
    upload_events_parser.add_argument("--bucket", default=DATA_BUCKET, help="S3 bucket")
    upload_events_parser.add_argument(
        "--file",
        default="data/event_ids.json",
        help="Event IDs file",
    )

    # configure-secret command
    secret_parser = subparsers.add_parser(
        "configure-secret", help="Configure ZwiftPower credentials"
    )
    secret_parser.add_argument("--secret-name", default=SECRET_NAME, help="Secret name")
    secret_parser.add_argument("--username", required=True, help="ZwiftPower username")
    secret_parser.add_argument("--password", required=True, help="ZwiftPower password")

    # trigger command
    trigger_parser = subparsers.add_parser(
        "trigger", help="Trigger Lambda function manually"
    )
    trigger_parser.add_argument(
        "function",
        choices=["fetcher", "processor"],
        help="Which Lambda to trigger",
    )

    # status command
    subparsers.add_parser("status", help="Show deployment status")

    # full-setup command
    full_parser = subparsers.add_parser("full-setup", help="Run full initial setup")
    full_parser.add_argument("--bucket", default=DATA_BUCKET, help="S3 bucket")
    full_parser.add_argument("--username", help="ZwiftPower username")
    full_parser.add_argument("--password", help="ZwiftPower password")

    args = parser.parse_args()

    if args.command == "upload-riders":
        success = upload_riders(args.bucket)
        sys.exit(0 if success else 1)

    elif args.command == "upload-events":
        success = upload_event_ids(args.bucket, Path(args.file))
        sys.exit(0 if success else 1)

    elif args.command == "configure-secret":
        success = configure_secret(args.secret_name, args.username, args.password)
        sys.exit(0 if success else 1)

    elif args.command == "trigger":
        function_name = (
            "kwcc-tdz-data-fetcher-prod"
            if args.function == "fetcher"
            else "kwcc-tdz-results-processor-prod"
        )
        success = trigger_lambda(function_name)
        sys.exit(0 if success else 1)

    elif args.command == "status":
        url = get_website_url()
        if url:
            logger.info(f"Website URL: {url}")
        else:
            logger.info("CDN stack not deployed yet")

    elif args.command == "full-setup":
        logger.info("=" * 50)
        logger.info("KWCC TdZ AWS Full Setup")
        logger.info("=" * 50)

        # Step 1: Upload riders
        logger.info("\n[1/3] Uploading rider registry...")
        if not upload_riders(args.bucket):
            logger.error("Failed to upload riders")
            sys.exit(1)

        # Step 2: Upload event IDs if available
        logger.info("\n[2/3] Uploading event IDs...")
        event_ids_file = Path("data/event_ids.json")
        if event_ids_file.exists():
            upload_event_ids(args.bucket, event_ids_file)
        else:
            logger.info("No event IDs file found, skipping")

        # Step 3: Configure credentials if provided
        if args.username and args.password:
            logger.info("\n[3/3] Configuring ZwiftPower credentials...")
            configure_secret(SECRET_NAME, args.username, args.password)
        else:
            logger.info("\n[3/3] Skipping credential configuration (not provided)")
            logger.info(
                "Run: scripts/aws_setup.py configure-secret --username ... --password ..."
            )

        logger.info("\n" + "=" * 50)
        logger.info("Setup complete!")
        url = get_website_url()
        if url:
            logger.info(f"Website URL: {url}")
        logger.info("=" * 50)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
