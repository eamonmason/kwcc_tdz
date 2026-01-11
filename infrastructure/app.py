#!/usr/bin/env python3
"""CDK app entry point for KWCC TdZ infrastructure."""

import aws_cdk as cdk

from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack

app = cdk.App()

# Environment configuration
env = cdk.Environment(
    region="eu-west-1",
)

# Get environment name from context or default to prod
environment = app.node.try_get_context("environment") or "prod"

# Create stacks in dependency order
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
