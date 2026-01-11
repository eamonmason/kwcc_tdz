#!/usr/bin/env python3
"""CDK app entry point for KWCC TdZ infrastructure."""

import aws_cdk as cdk

from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack
from stacks.github_actions_stack import GitHubActionsStack

app = cdk.App()

# Environment configuration
env = cdk.Environment(
    region="eu-west-1",
)

# Get environment name from context or default to prod
environment = app.node.try_get_context("environment") or "prod"

# GitHub repository configuration
github_org = "eamonmason"
github_repo = "kwcc_tdz"

# 0. GitHub Actions IAM role (no dependencies, can be deployed independently)
github_actions_stack = GitHubActionsStack(
    app,
    f"KwccTdz{environment.capitalize()}GitHubActionsStack",
    env=env,
    github_org=github_org,
    github_repo=github_repo,
    environment=environment,
)

# 1. Data stack - S3 buckets, Secrets Manager, and CloudFront CDN
data_stack = DataStack(
    app,
    f"KwccTdz{environment.capitalize()}DataStack",
    env=env,
    environment=environment,
)

# 2. Compute stack - Lambda functions (depends on data_stack)
compute_stack = ComputeStack(
    app,
    f"KwccTdz{environment.capitalize()}ComputeStack",
    env=env,
    environment=environment,
    data_bucket=data_stack.data_bucket,
    website_bucket=data_stack.website_bucket,
    zwiftpower_secret=data_stack.zwiftpower_secret,
    cloudfront_distribution_id=data_stack.distribution.distribution_id,
)

# Add dependencies
compute_stack.add_dependency(data_stack)

app.synth()
