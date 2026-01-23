"""Compute stack with Lambda functions and EventBridge."""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
)
from aws_cdk import (
    aws_cloudwatch_actions as cloudwatch_actions,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_sns as sns,
)
from constructs import Construct


class ComputeStack(Stack):
    """Stack for compute resources (Lambda, EventBridge)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment: str,
        data_bucket: s3.IBucket,
        website_bucket: s3.IBucket,
        zwiftpower_secret: secretsmanager.ISecret,
        cloudfront_distribution_id: str = "",
        enable_schedule: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Lambda layer for dependencies
        # Use x86_64 architecture to match the bundling platform
        # Exposed as property for sharing with other stacks
        self.dependencies_layer = lambda_.LayerVersion(
            self,
            "DependenciesLayer",
            code=lambda_.Code.from_asset(
                "../",
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "platform": "linux/amd64",
                    "command": [
                        "bash",
                        "-c",
                        "pip install -r requirements-lambda.txt -t /asset-output/python "
                        "--platform manylinux2014_x86_64 --only-binary=:all: && "
                        "cp -r src /asset-output/python/",
                    ],
                },
            ),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            compatible_architectures=[lambda_.Architecture.X86_64],
            description="KWCC TdZ dependencies",
        )

        # Results Processor Lambda (defined first so we can reference it)
        # Include both src/ and static/ directories for website generation
        self.results_processor = lambda_.Function(
            self,
            "ResultsProcessorLambda",
            function_name=f"kwcc-tdz-results-processor-{environment}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="src.lambda_handlers.processor.handler",
            code=lambda_.Code.from_asset(
                "../",
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "command": [
                        "bash",
                        "-c",
                        "cp -r src static /asset-output/",
                    ],
                },
            ),
            layers=[self.dependencies_layer],
            timeout=Duration.minutes(2),
            memory_size=256,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "WEBSITE_BUCKET": website_bucket.bucket_name,
                "CLOUDFRONT_DISTRIBUTION_ID": cloudfront_distribution_id,
                "ENVIRONMENT": environment,
            },
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )

        # Grant permissions to processor
        data_bucket.grant_read_write(self.results_processor)
        website_bucket.grant_read_write(self.results_processor)

        # Grant CloudFront invalidation permissions
        if cloudfront_distribution_id:
            self.results_processor.add_to_role_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["cloudfront:CreateInvalidation"],
                    resources=[
                        f"arn:aws:cloudfront::{self.account}:distribution/{cloudfront_distribution_id}"
                    ],
                )
            )

        # Data Fetcher Lambda
        self.data_fetcher = lambda_.Function(
            self,
            "DataFetcherLambda",
            function_name=f"kwcc-tdz-data-fetcher-{environment}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="src.lambda_handlers.data_fetcher.handler",
            code=lambda_.Code.from_asset("../src"),
            layers=[self.dependencies_layer],
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "WEBSITE_BUCKET": website_bucket.bucket_name,
                "ZWIFTPOWER_SECRET_ARN": zwiftpower_secret.secret_arn,
                "PROCESSOR_LAMBDA_ARN": self.results_processor.function_arn,
                "ENVIRONMENT": environment,
            },
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )

        # Grant permissions
        data_bucket.grant_read_write(self.data_fetcher)
        website_bucket.grant_read_write(self.data_fetcher)
        zwiftpower_secret.grant_read(self.data_fetcher)

        # Grant data fetcher permission to invoke processor Lambda
        self.results_processor.grant_invoke(self.data_fetcher)

        # EventBridge rule for hourly execution (cron-based for precise timing)
        # Runs at 5 minutes past every hour to allow events to complete
        # Only enabled for production (CI uses manual invocation)
        if enable_schedule:
            hourly_rule = events.Rule(
                self,
                "HourlyFetchRule",
                rule_name=f"kwcc-tdz-hourly-fetch-{environment}",
                schedule=events.Schedule.cron(minute="5", hour="*"),
                description="Fetch ZwiftPower results hourly at :05 past the hour",
            )

            hourly_rule.add_target(
                targets.LambdaFunction(
                    self.data_fetcher,
                    retry_attempts=2,
                )
            )

        # Outputs
        CfnOutput(
            self,
            "DataFetcherArn",
            value=self.data_fetcher.function_arn,
            description="ARN of data fetcher Lambda",
        )

        CfnOutput(
            self,
            "ResultsProcessorArn",
            value=self.results_processor.function_arn,
            description="ARN of results processor Lambda",
        )

        # SNS topic for alerts
        self.alerts_topic = sns.Topic(
            self,
            "AlertsTopic",
            topic_name=f"kwcc-tdz-alerts-{environment}",
            display_name="KWCC TdZ Alerts",
        )

        # CloudWatch Alarms
        # Data fetcher errors
        cloudwatch.Alarm(
            self,
            "DataFetcherErrorsAlarm",
            alarm_name=f"kwcc-tdz-data-fetcher-errors-{environment}",
            alarm_description="Data fetcher Lambda errors",
            metric=self.data_fetcher.metric_errors(
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))

        # Data fetcher throttles
        cloudwatch.Alarm(
            self,
            "DataFetcherThrottlesAlarm",
            alarm_name=f"kwcc-tdz-data-fetcher-throttles-{environment}",
            alarm_description="Data fetcher Lambda throttles",
            metric=self.data_fetcher.metric_throttles(
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))

        # Processor errors
        cloudwatch.Alarm(
            self,
            "ProcessorErrorsAlarm",
            alarm_name=f"kwcc-tdz-processor-errors-{environment}",
            alarm_description="Results processor Lambda errors",
            metric=self.results_processor.metric_errors(
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(cloudwatch_actions.SnsAction(self.alerts_topic))

        CfnOutput(
            self,
            "AlertsTopicArn",
            value=self.alerts_topic.topic_arn,
            description="ARN of alerts SNS topic",
        )
