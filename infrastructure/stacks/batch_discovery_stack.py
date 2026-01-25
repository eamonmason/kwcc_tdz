"""CDK stack for batch discovery Lambda with S3 checkpointing.

This stack replaces the Step Functions pipeline in discovery_stack.py with a
simpler, more cost-effective single Lambda that uses S3-based checkpointing
for incremental progress.
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class BatchDiscoveryStack(Stack):
    """
    Single Lambda stack for batch event discovery.

    Replaces the Step Functions pipeline with a simpler architecture:
    - Single Lambda with 15-minute timeout
    - S3-based checkpointing for incremental progress
    - EventBridge rule for scheduled execution
    - No DynamoDB table required

    Benefits:
    - ~70% cost reduction compared to Step Functions
    - Simpler architecture (1 Lambda vs 6)
    - Better failure recovery (checkpoint preserves progress)
    - Easier debugging (single CloudWatch log group)
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        data_bucket: s3.IBucket,
        zwiftpower_secret: secretsmanager.ISecret,
        processor_lambda: lambda_.IFunction,
        dependencies_layer: lambda_.ILayerVersion,
        env_name: str = "prod",
        enable_schedule: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._env_name = env_name

        # Batch Discovery Lambda
        # 15-minute timeout allows for significant processing per invocation
        # Progress is saved to S3 checkpoint, so timeout is safe
        # Bundle src/ directory so handler can import src.lambda_handlers...
        self.batch_discovery_lambda = lambda_.Function(
            self,
            "BatchDiscoveryFunction",
            function_name=f"kwcc-tdz-batch-discovery-{env_name}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="src.lambda_handlers.batch_discovery.handler",
            code=lambda_.Code.from_asset(
                "../",
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "command": [
                        "bash",
                        "-c",
                        "cp -r src /asset-output/",
                    ],
                },
            ),
            layers=[dependencies_layer],
            timeout=Duration.minutes(15),
            memory_size=1024,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "ZWIFTPOWER_SECRET_ARN": zwiftpower_secret.secret_arn,
                "PROCESSOR_LAMBDA_ARN": processor_lambda.function_arn,
            },
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )

        # Grant permissions
        data_bucket.grant_read_write(self.batch_discovery_lambda)
        zwiftpower_secret.grant_read(self.batch_discovery_lambda)
        processor_lambda.grant_invoke(self.batch_discovery_lambda)

        # EventBridge rule for hourly execution
        # Only enabled for production (CI uses manual invocation)
        if enable_schedule:
            self.hourly_rule = events.Rule(
                self,
                "BatchDiscoveryHourlyRule",
                rule_name=f"kwcc-tdz-batch-discovery-hourly-{env_name}",
                schedule=events.Schedule.cron(minute="30", hour="*"),
                description=(
                    "Run batch discovery hourly at :30 past the hour "
                    "(offset from data fetcher at :05)"
                ),
            )

            self.hourly_rule.add_target(
                targets.LambdaFunction(
                    self.batch_discovery_lambda,
                    retry_attempts=2,
                )
            )
        else:
            self.hourly_rule = None

        # Outputs
        CfnOutput(
            self,
            "BatchDiscoveryLambdaArn",
            value=self.batch_discovery_lambda.function_arn,
            description="ARN of the batch discovery Lambda",
        )

        CfnOutput(
            self,
            "BatchDiscoveryLambdaName",
            value=self.batch_discovery_lambda.function_name,
            description="Name of the batch discovery Lambda",
        )
