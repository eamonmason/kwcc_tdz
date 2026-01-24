#!/usr/bin/env python3
"""CDK app entry point for KWCC TdZ infrastructure."""

import os

import aws_cdk as cdk
from stacks.batch_discovery_stack import BatchDiscoveryStack
from stacks.certificate_stack import CertificateStack
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack
from stacks.discovery_stack import DiscoveryStack
from stacks.github_actions_stack import GitHubActionsStack

app = cdk.App()

# Account configuration (required for cross-region certificate)
account = os.environ.get("CDK_DEFAULT_ACCOUNT")

# Environment configurations
env_eu = cdk.Environment(account=account, region="eu-west-1")
env_us = cdk.Environment(account=account, region="us-east-1")

# Get environment name from context or default to prod
environment = app.node.try_get_context("environment") or "prod"

# GitHub repository configuration
github_org = "eamonmason"
github_repo = "kwcc_tdz"

# Environment-specific configuration
# prod: Full production environment with custom domain and scheduled execution
# ci: CI/staging environment with custom domain, shared credentials, manual execution only
if environment == "prod":
    domain_name = "tdz.kingstonwheelers.cc"
    existing_secret_arn = None  # Create new secret
    enable_schedule = True  # Enable hourly EventBridge trigger
elif environment == "ci":
    domain_name = "ci-tdz.kingstonwheelers.cc"
    # Reference prod's secret (must be deployed after prod)
    existing_secret_arn = f"arn:aws:secretsmanager:eu-west-1:{account}:secret:kwcc-tdz/zwiftpower-credentials-prod"
    enable_schedule = False  # Manual invocation only for CI
else:
    # Other environments (dev, local testing, etc.)
    domain_name = None  # No custom domain
    existing_secret_arn = None
    enable_schedule = False

# 0. GitHub Actions IAM role (no dependencies, can be deployed independently)
github_actions_stack = GitHubActionsStack(
    app,
    f"KwccTdz{environment.capitalize()}GitHubActionsStack",
    env=env_eu,
    github_org=github_org,
    github_repo=github_repo,
    environment=environment,
)

# 1. Certificate stack in us-east-1 (required for CloudFront with custom domain)
# Only create if we have a custom domain
certificate_stack = None
certificate_arn = None
if domain_name:
    certificate_stack = CertificateStack(
        app,
        f"KwccTdz{environment.capitalize()}CertificateStack",
        env=env_us,
        domain_name=domain_name,
        cross_region_references=True,
    )
    certificate_arn = certificate_stack.certificate.certificate_arn

# 2. Data stack - S3 buckets, Secrets Manager, and CloudFront CDN
data_stack = DataStack(
    app,
    f"KwccTdz{environment.capitalize()}DataStack",
    env=env_eu,
    environment=environment,
    domain_name=domain_name,
    certificate_arn=certificate_arn,
    existing_secret_arn=existing_secret_arn,
    cross_region_references=bool(domain_name),
)
if certificate_stack:
    data_stack.add_dependency(certificate_stack)

# 3. Compute stack - Lambda functions (depends on data_stack)
compute_stack = ComputeStack(
    app,
    f"KwccTdz{environment.capitalize()}ComputeStack",
    env=env_eu,
    environment=environment,
    data_bucket=data_stack.data_bucket,
    website_bucket=data_stack.website_bucket,
    zwiftpower_secret=data_stack.zwiftpower_secret,
    cloudfront_distribution_id=data_stack.distribution.distribution_id,
    enable_schedule=enable_schedule,
)
compute_stack.add_dependency(data_stack)

# 4. Discovery stack - Step Functions pipeline for distributed event discovery
# NOTE: This is being replaced by BatchDiscoveryStack. Both coexist during migration.
discovery_stack = DiscoveryStack(
    app,
    f"KwccTdz{environment.capitalize()}DiscoveryStack",
    env=env_eu,
    data_bucket=data_stack.data_bucket,
    zwiftpower_secret=data_stack.zwiftpower_secret,
    processor_lambda=compute_stack.results_processor,
    dependencies_layer=compute_stack.dependencies_layer,
    env_name=environment,
)
discovery_stack.add_dependency(compute_stack)

# 5. Batch Discovery stack - Simplified single Lambda replacement for Step Functions
# This stack provides the same functionality with lower cost and complexity:
# - Single Lambda vs 6 Lambdas + Step Functions state machine
# - S3 checkpointing for incremental progress (no DynamoDB)
# - ~70% cost reduction
batch_discovery_stack = BatchDiscoveryStack(
    app,
    f"KwccTdz{environment.capitalize()}BatchDiscoveryStack",
    env=env_eu,
    data_bucket=data_stack.data_bucket,
    zwiftpower_secret=data_stack.zwiftpower_secret,
    processor_lambda=compute_stack.results_processor,
    dependencies_layer=compute_stack.dependencies_layer,
    env_name=environment,
    enable_schedule=enable_schedule,
)
batch_discovery_stack.add_dependency(compute_stack)

app.synth()
