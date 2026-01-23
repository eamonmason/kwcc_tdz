"""Step Functions stack for distributed event discovery."""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct


class DiscoveryStack(Stack):
    """Step Functions pipeline for rider-centric event discovery."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        data_bucket: s3.IBucket,
        zwiftpower_secret: secretsmanager.ISecret,
        processor_lambda: lambda_.IFunction,
        dependencies_layer: lambda_.ILayerVersion,
        environment: str = "prod",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.environment = environment

        # 1. DynamoDB staging table for discovered events
        self.staging_table = dynamodb.Table(
            self,
            "DiscoveredEventsStaging",
            table_name=f"kwcc-tdz-discovered-events-{environment}",
            partition_key=dynamodb.Attribute(
                name="event_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="discovered_by", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        # Common Lambda configuration
        common_lambda_props = {
            "runtime": lambda_.Runtime.PYTHON_3_12,
            "architecture": lambda_.Architecture.X86_64,
            "layers": [dependencies_layer],
            "log_retention": logs.RetentionDays.TWO_WEEKS,
        }

        # 2. Load Config Lambda
        self.load_config_lambda = lambda_.Function(
            self,
            "LoadConfigFunction",
            function_name=f"kwcc-tdz-discovery-load-config-{environment}",
            handler="src.lambda_handlers.discovery.load_config.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "ZWIFTPOWER_SECRET_ARN": zwiftpower_secret.secret_arn,
            },
            **common_lambda_props,
        )
        data_bucket.grant_read(self.load_config_lambda)
        zwiftpower_secret.grant_read(self.load_config_lambda)

        # 3. Discover Rider Events Lambda
        self.discover_rider_lambda = lambda_.Function(
            self,
            "DiscoverRiderFunction",
            function_name=f"kwcc-tdz-discovery-rider-events-{environment}",
            handler="src.lambda_handlers.discovery.discover_rider_events.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(60),  # Per-rider timeout
            memory_size=256,
            environment={
                "STAGING_TABLE": self.staging_table.table_name,
                "ZWIFTPOWER_SECRET_ARN": zwiftpower_secret.secret_arn,
            },
            **common_lambda_props,
        )
        self.staging_table.grant_write_data(self.discover_rider_lambda)
        zwiftpower_secret.grant_read(self.discover_rider_lambda)

        # 4. Aggregate Events Lambda
        self.aggregate_lambda = lambda_.Function(
            self,
            "AggregateEventsFunction",
            function_name=f"kwcc-tdz-discovery-aggregate-{environment}",
            handler="src.lambda_handlers.discovery.aggregate_events.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(60),
            memory_size=256,
            environment={
                "STAGING_TABLE": self.staging_table.table_name,
            },
            **common_lambda_props,
        )
        self.staging_table.grant_read_data(self.aggregate_lambda)

        # 5. Fetch Event Results Lambda
        self.fetch_event_lambda = lambda_.Function(
            self,
            "FetchEventFunction",
            function_name=f"kwcc-tdz-discovery-fetch-event-{environment}",
            handler="src.lambda_handlers.discovery.fetch_event_results.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.seconds(120),  # Per-event timeout
            memory_size=512,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "ZWIFTPOWER_SECRET_ARN": zwiftpower_secret.secret_arn,
            },
            **common_lambda_props,
        )
        data_bucket.grant_read_write(self.fetch_event_lambda)
        zwiftpower_secret.grant_read(self.fetch_event_lambda)

        # 6. Merge and Process Lambda
        self.merge_process_lambda = lambda_.Function(
            self,
            "MergeProcessFunction",
            function_name=f"kwcc-tdz-discovery-merge-process-{environment}",
            handler="src.lambda_handlers.discovery.merge_and_process.handler",
            code=lambda_.Code.from_asset("../src"),
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "ZWIFTPOWER_SECRET_ARN": zwiftpower_secret.secret_arn,
                "PROCESSOR_LAMBDA_ARN": processor_lambda.function_arn,
            },
            **common_lambda_props,
        )
        data_bucket.grant_read_write(self.merge_process_lambda)
        zwiftpower_secret.grant_read(self.merge_process_lambda)
        processor_lambda.grant_invoke(self.merge_process_lambda)

        # 7. Create Step Function State Machine
        self.state_machine = self._create_state_machine()

        # Outputs
        CfnOutput(
            self,
            "StagingTableName",
            value=self.staging_table.table_name,
            description="DynamoDB staging table for discovered events",
        )

        CfnOutput(
            self,
            "StateMachineArn",
            value=self.state_machine.state_machine_arn,
            description="ARN of the discovery pipeline state machine",
        )

    def _create_state_machine(self) -> sfn.StateMachine:
        """Create the Step Function state machine."""

        # Step 1: Load Config
        load_config_task = tasks.LambdaInvoke(
            self,
            "LoadConfig",
            lambda_function=self.load_config_lambda,
            output_path="$.Payload",
            result_path="$",
        )

        # Step 2: Discover Rider Events (Map with rate limiting)
        discover_rider_task = tasks.LambdaInvoke(
            self,
            "DiscoverRiderEventsTask",
            lambda_function=self.discover_rider_lambda,
            output_path="$.Payload",
        )

        # Add retry for rate limiting
        discover_rider_task.add_retry(
            errors=["TooManyRequestsException", "Lambda.ServiceException"],
            interval=Duration.seconds(5),
            max_attempts=3,
            backoff_rate=2,
        )

        discover_map = sfn.Map(
            self,
            "DiscoverRiderEventsMap",
            max_concurrency=5,  # Rate limiting: 5 concurrent riders
            items_path="$.riders",
            item_selector={
                "rider.$": "$$.Map.Item.Value",
                "stages.$": "$.stages",
            },
            result_path="$.discovered",
        )
        discover_map.item_processor(discover_rider_task)

        # Step 3: Aggregate Events
        aggregate_task = tasks.LambdaInvoke(
            self,
            "AggregateEvents",
            lambda_function=self.aggregate_lambda,
            output_path="$.Payload",
        )

        # Step 4: Fetch Event Results (Map with rate limiting)
        fetch_event_task = tasks.LambdaInvoke(
            self,
            "FetchEventResultsTask",
            lambda_function=self.fetch_event_lambda,
            output_path="$.Payload",
        )

        # Add retry for rate limiting
        fetch_event_task.add_retry(
            errors=["TooManyRequestsException", "Lambda.ServiceException"],
            interval=Duration.seconds(5),
            max_attempts=3,
            backoff_rate=2,
        )

        fetch_map = sfn.Map(
            self,
            "FetchEventResultsMap",
            max_concurrency=3,  # Rate limiting: 3 concurrent events
            items_path="$.unique_events",
            result_path="$.fetched_events",
        )
        fetch_map.item_processor(fetch_event_task)

        # Step 5: Merge and Process
        merge_process_task = tasks.LambdaInvoke(
            self,
            "MergeAndProcess",
            lambda_function=self.merge_process_lambda,
            output_path="$.Payload",
        )

        # Add a check for empty riders (no active stages)
        check_riders = sfn.Choice(self, "CheckRiders")
        check_riders.when(
            sfn.Condition.number_equals("$.riders.length()", 0),
            sfn.Pass(self, "NoActiveStages", comment="No active stages to process"),
        )

        # Chain the steps
        definition = load_config_task.next(check_riders)

        # When there are riders, continue with the pipeline
        check_riders.otherwise(
            discover_map.next(aggregate_task).next(fetch_map).next(merge_process_task)
        )

        return sfn.StateMachine(
            self,
            "DiscoveryPipeline",
            state_machine_name=f"kwcc-tdz-discovery-pipeline-{self.environment}",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(30),
            tracing_enabled=True,
        )
