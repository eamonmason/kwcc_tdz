"""GitHub Actions OIDC IAM Role Stack.

Creates a dedicated IAM role for GitHub Actions to deploy this application
using OIDC federation (no long-lived credentials needed).
"""

from aws_cdk import (
    CfnOutput,
    Stack,
)
from aws_cdk import (
    aws_iam as iam,
)
from constructs import Construct


class GitHubActionsStack(Stack):
    """Stack for GitHub Actions deployment role using OIDC."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        github_org: str,
        github_repo: str,
        environment: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Reference existing GitHub OIDC provider
        github_provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
            self,
            "GitHubProvider",
            f"arn:aws:iam::{self.account}:oidc-provider/token.actions.githubusercontent.com",
        )

        # Create trust policy for GitHub Actions
        # Only allow this specific repo on main branch
        github_actions_role = iam.Role(
            self,
            "GitHubActionsRole",
            role_name=f"kwcc-tdz-github-actions-{environment}",
            description=f"Role for GitHub Actions to deploy kwcc-tdz ({environment})",
            assumed_by=iam.FederatedPrincipal(
                github_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                    "StringLike": {
                        # Allow main branch, develop branch, and pull requests
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{github_org}/{github_repo}:ref:refs/heads/main",
                            f"repo:{github_org}/{github_repo}:ref:refs/heads/develop",
                            f"repo:{github_org}/{github_repo}:pull_request",
                        ],
                    },
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
            max_session_duration=None,  # Use default (1 hour)
        )

        # CDK Bootstrap permissions (read CDK toolkit stack)
        # Support eu-west-1 (main) and us-east-1 (for CloudFront certificates)
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="CDKBootstrapRead",
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudformation:DescribeStacks",
                    "ssm:GetParameter",
                ],
                resources=[
                    f"arn:aws:cloudformation:eu-west-1:{self.account}:stack/CDKToolkit/*",
                    f"arn:aws:ssm:eu-west-1:{self.account}:parameter/cdk-bootstrap/*",
                    f"arn:aws:cloudformation:us-east-1:{self.account}:stack/CDKToolkit/*",
                    f"arn:aws:ssm:us-east-1:{self.account}:parameter/cdk-bootstrap/*",
                ],
            )
        )

        # CloudFormation permissions for application stacks
        # Support eu-west-1 (main) and us-east-1 (for CloudFront certificates)
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudFormationDeploy",
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudformation:CreateStack",
                    "cloudformation:UpdateStack",
                    "cloudformation:DeleteStack",
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:GetTemplate",
                    "cloudformation:GetTemplateSummary",
                    "cloudformation:ListStackResources",
                    "cloudformation:CreateChangeSet",
                    "cloudformation:DeleteChangeSet",
                    "cloudformation:DescribeChangeSet",
                    "cloudformation:ExecuteChangeSet",
                ],
                resources=[
                    f"arn:aws:cloudformation:eu-west-1:{self.account}:stack/KwccTdz*/*",
                    f"arn:aws:cloudformation:us-east-1:{self.account}:stack/KwccTdz*/*",
                ],
            )
        )

        # S3 permissions for CDK assets bucket
        # Support eu-west-1 (main) and us-east-1 (for CloudFront certificates)
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="CDKAssetsBucket",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                ],
                resources=[
                    f"arn:aws:s3:::cdk-*-assets-{self.account}-eu-west-1",
                    f"arn:aws:s3:::cdk-*-assets-{self.account}-eu-west-1/*",
                    f"arn:aws:s3:::cdk-*-assets-{self.account}-us-east-1",
                    f"arn:aws:s3:::cdk-*-assets-{self.account}-us-east-1/*",
                ],
            )
        )

        # S3 permissions for application buckets
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="ApplicationBuckets",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:CreateBucket",
                    "s3:DeleteBucket",
                    "s3:GetBucketPolicy",
                    "s3:PutBucketPolicy",
                    "s3:DeleteBucketPolicy",
                    "s3:GetBucketAcl",
                    "s3:PutBucketAcl",
                    "s3:GetBucketCORS",
                    "s3:PutBucketCORS",
                    "s3:GetBucketVersioning",
                    "s3:PutBucketVersioning",
                    "s3:GetBucketPublicAccessBlock",
                    "s3:PutBucketPublicAccessBlock",
                    "s3:GetEncryptionConfiguration",
                    "s3:PutEncryptionConfiguration",
                    "s3:GetBucketTagging",
                    "s3:PutBucketTagging",
                    "s3:GetLifecycleConfiguration",
                    "s3:PutLifecycleConfiguration",
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                ],
                resources=[
                    "arn:aws:s3:::kwcc-tdz-*",
                    "arn:aws:s3:::kwcc-tdz-*/*",
                ],
            )
        )

        # Lambda permissions
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="LambdaManagement",
                effect=iam.Effect.ALLOW,
                actions=[
                    "lambda:CreateFunction",
                    "lambda:UpdateFunctionCode",
                    "lambda:UpdateFunctionConfiguration",
                    "lambda:DeleteFunction",
                    "lambda:GetFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:ListVersionsByFunction",
                    "lambda:PublishVersion",
                    "lambda:CreateAlias",
                    "lambda:UpdateAlias",
                    "lambda:DeleteAlias",
                    "lambda:AddPermission",
                    "lambda:RemovePermission",
                    "lambda:GetPolicy",
                    "lambda:InvokeFunction",
                    "lambda:TagResource",
                    "lambda:UntagResource",
                    "lambda:ListTags",
                    "lambda:PutFunctionEventInvokeConfig",
                    "lambda:DeleteFunctionEventInvokeConfig",
                    "lambda:GetFunctionEventInvokeConfig",
                ],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:function:kwcc-tdz-*",
                ],
            )
        )

        # Lambda Layer permissions
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="LambdaLayers",
                effect=iam.Effect.ALLOW,
                actions=[
                    "lambda:PublishLayerVersion",
                    "lambda:DeleteLayerVersion",
                    "lambda:GetLayerVersion",
                    "lambda:ListLayerVersions",
                ],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:layer:*",
                ],
            )
        )

        # IAM role management for Lambda execution roles
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="IAMRoleManagement",
                effect=iam.Effect.ALLOW,
                actions=[
                    "iam:CreateRole",
                    "iam:DeleteRole",
                    "iam:GetRole",
                    "iam:UpdateRole",
                    "iam:PassRole",
                    "iam:AttachRolePolicy",
                    "iam:DetachRolePolicy",
                    "iam:PutRolePolicy",
                    "iam:DeleteRolePolicy",
                    "iam:GetRolePolicy",
                    "iam:ListRolePolicies",
                    "iam:ListAttachedRolePolicies",
                    "iam:TagRole",
                    "iam:UntagRole",
                ],
                resources=[
                    f"arn:aws:iam::{self.account}:role/KwccTdz*",
                ],
            )
        )

        # CDK bootstrap roles - required for CDK deploy
        # Support eu-west-1 (main) and us-east-1 (for CloudFront certificates)
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="CDKBootstrapRoles",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sts:AssumeRole",
                    "iam:PassRole",
                ],
                resources=[
                    f"arn:aws:iam::{self.account}:role/cdk-*-{self.account}-eu-west-1",
                    f"arn:aws:iam::{self.account}:role/cdk-*-{self.account}-us-east-1",
                ],
            )
        )

        # CloudFront permissions
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudFrontManagement",
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudfront:CreateDistribution",
                    "cloudfront:UpdateDistribution",
                    "cloudfront:DeleteDistribution",
                    "cloudfront:GetDistribution",
                    "cloudfront:GetDistributionConfig",
                    "cloudfront:TagResource",
                    "cloudfront:UntagResource",
                    "cloudfront:ListTagsForResource",
                    "cloudfront:CreateInvalidation",
                    "cloudfront:GetInvalidation",
                    "cloudfront:ListInvalidations",
                    "cloudfront:CreateOriginAccessControl",
                    "cloudfront:UpdateOriginAccessControl",
                    "cloudfront:DeleteOriginAccessControl",
                    "cloudfront:GetOriginAccessControl",
                    "cloudfront:ListOriginAccessControls",
                ],
                resources=["*"],  # CloudFront resources are global
            )
        )

        # ACM Certificate Manager permissions (for CloudFront certificates in us-east-1)
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="ACMCertificateManagement",
                effect=iam.Effect.ALLOW,
                actions=[
                    "acm:RequestCertificate",
                    "acm:DeleteCertificate",
                    "acm:DescribeCertificate",
                    "acm:ListCertificates",
                    "acm:AddTagsToCertificate",
                    "acm:RemoveTagsFromCertificate",
                    "acm:ListTagsForCertificate",
                ],
                resources=[
                    f"arn:aws:acm:us-east-1:{self.account}:certificate/*",
                ],
            )
        )

        # EventBridge permissions
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="EventBridgeManagement",
                effect=iam.Effect.ALLOW,
                actions=[
                    "events:PutRule",
                    "events:DeleteRule",
                    "events:DescribeRule",
                    "events:EnableRule",
                    "events:DisableRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:ListTargetsByRule",
                    "events:TagResource",
                    "events:UntagResource",
                ],
                resources=[
                    f"arn:aws:events:{self.region}:{self.account}:rule/kwcc-tdz-*",
                ],
            )
        )

        # CloudWatch Logs permissions
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:DeleteLogGroup",
                    "logs:DescribeLogGroups",
                    "logs:PutRetentionPolicy",
                    "logs:DeleteRetentionPolicy",
                    "logs:TagLogGroup",
                    "logs:UntagLogGroup",
                    "logs:TagResource",
                    "logs:UntagResource",
                    "logs:ListTagsForResource",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/lambda/kwcc-tdz-*",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/lambda/kwcc-tdz-*:*",
                ],
            )
        )

        # CloudWatch Alarms permissions
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchAlarms",
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudwatch:PutMetricAlarm",
                    "cloudwatch:DeleteAlarms",
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:TagResource",
                    "cloudwatch:UntagResource",
                ],
                resources=[
                    f"arn:aws:cloudwatch:{self.region}:{self.account}:alarm:kwcc-tdz-*",
                ],
            )
        )

        # SNS permissions
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="SNSManagement",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sns:CreateTopic",
                    "sns:DeleteTopic",
                    "sns:GetTopicAttributes",
                    "sns:SetTopicAttributes",
                    "sns:Subscribe",
                    "sns:Unsubscribe",
                    "sns:TagResource",
                    "sns:UntagResource",
                    "sns:ListTagsForResource",
                ],
                resources=[
                    f"arn:aws:sns:{self.region}:{self.account}:kwcc-tdz-*",
                ],
            )
        )

        # Secrets Manager permissions (read-only for existing secret)
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="SecretsManagerManagement",
                effect=iam.Effect.ALLOW,
                actions=[
                    "secretsmanager:CreateSecret",
                    "secretsmanager:DeleteSecret",
                    "secretsmanager:DescribeSecret",
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:UpdateSecret",
                    "secretsmanager:TagResource",
                    "secretsmanager:UntagResource",
                ],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:kwcc-tdz/*",
                ],
            )
        )

        # ECR permissions (for CDK asset images if needed)
        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="ECRAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
        )

        github_actions_role.add_to_policy(
            iam.PolicyStatement(
                sid="ECRRepository",
                effect=iam.Effect.ALLOW,
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:PutImage",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                ],
                resources=[
                    f"arn:aws:ecr:{self.region}:{self.account}:repository/cdk-*",
                ],
            )
        )

        # Output the role ARN
        CfnOutput(
            self,
            "GitHubActionsRoleArn",
            value=github_actions_role.role_arn,
            description="ARN of the GitHub Actions deployment role",
            export_name=f"kwcc-tdz-github-actions-role-arn-{environment}",
        )

        CfnOutput(
            self,
            "GitHubActionsRoleName",
            value=github_actions_role.role_name,
            description="Name of the GitHub Actions deployment role",
        )

        self.role = github_actions_role
