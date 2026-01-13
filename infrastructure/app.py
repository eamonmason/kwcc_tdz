#!/usr/bin/env python3
"""CDK app entry point for KWCC TdZ infrastructure."""

import os

import aws_cdk as cdk
from stacks.certificate_stack import CertificateStack
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack
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
domain_name = "tdz.kingstonwheelers.cc"

# 0. GitHub Actions IAM role (no dependencies, can be deployed independently)
github_actions_stack = GitHubActionsStack(
    app,
    f"KwccTdz{environment.capitalize()}GitHubActionsStack",
    env=env_eu,
    github_org=github_org,
    github_repo=github_repo,
    environment=environment,
)

# 1. Certificate stack in us-east-1 (required for CloudFront)
certificate_stack = CertificateStack(
    app,
    f"KwccTdz{environment.capitalize()}CertificateStack",
    env=env_us,
    domain_name=domain_name,
    cross_region_references=True,
)

# 2. Data stack - S3 buckets, Secrets Manager, and CloudFront CDN
data_stack = DataStack(
    app,
    f"KwccTdz{environment.capitalize()}DataStack",
    env=env_eu,
    environment=environment,
    domain_name=domain_name,
    certificate_arn=certificate_stack.certificate.certificate_arn,
    cross_region_references=True,
)
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
)
compute_stack.add_dependency(data_stack)

app.synth()
