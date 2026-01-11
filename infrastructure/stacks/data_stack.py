"""Data stack with S3 buckets, Secrets Manager, and CloudFront CDN."""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class DataStack(Stack):
    """Stack for data storage and CDN resources."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment: str = "prod",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # S3 bucket for raw data and processed results
        self.data_bucket = s3.Bucket(
            self,
            "DataBucket",
            bucket_name=f"kwcc-tdz-2026-data-{environment}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="CleanupOldVersions",
                    noncurrent_version_expiration=Duration.days(30),
                ),
            ],
        )

        # S3 bucket for static website
        self.website_bucket = s3.Bucket(
            self,
            "WebsiteBucket",
            bucket_name=f"kwcc-tdz-2026-website-{environment}",
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Secrets Manager for ZwiftPower credentials
        self.zwiftpower_secret = secretsmanager.Secret(
            self,
            "ZwiftPowerSecret",
            secret_name=f"kwcc-tdz/zwiftpower-credentials-{environment}",
            description="ZwiftPower credentials for KWCC TdZ results fetcher",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": ""}',
                generate_string_key="password",
                exclude_punctuation=True,
            ),
        )

        # CloudFront distribution for website
        # Using S3BucketOrigin with OAC (Origin Access Control)
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            self.website_bucket,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "WebsiteDistribution",
            comment=f"KWCC Tour de Zwift 2026 ({environment})",
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD,
            ),
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(10),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(10),
                ),
            ],
        )

        # Outputs
        CfnOutput(
            self,
            "DataBucketName",
            value=self.data_bucket.bucket_name,
            description="S3 bucket for raw and processed data",
        )

        CfnOutput(
            self,
            "WebsiteBucketName",
            value=self.website_bucket.bucket_name,
            description="S3 bucket for static website",
        )

        CfnOutput(
            self,
            "ZwiftPowerSecretArn",
            value=self.zwiftpower_secret.secret_arn,
            description="ARN of ZwiftPower credentials secret",
        )

        CfnOutput(
            self,
            "DistributionId",
            value=self.distribution.distribution_id,
            description="CloudFront distribution ID",
        )

        CfnOutput(
            self,
            "DistributionDomainName",
            value=self.distribution.distribution_domain_name,
            description="CloudFront distribution domain name",
        )

        CfnOutput(
            self,
            "WebsiteUrl",
            value=f"https://{self.distribution.distribution_domain_name}",
            description="Website URL",
        )
