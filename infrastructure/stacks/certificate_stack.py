"""Certificate stack for CloudFront (must be in us-east-1)."""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_certificatemanager as acm
from constructs import Construct


class CertificateStack(Stack):
    """Stack for ACM certificate in us-east-1 (required for CloudFront)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        domain_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ACM Certificate for custom domain
        # This stack MUST be deployed in us-east-1 for CloudFront to use it
        self.certificate = acm.Certificate(
            self,
            "WebsiteCertificate",
            domain_name=domain_name,
            validation=acm.CertificateValidation.from_dns(),
        )

        # Output certificate ARN for cross-stack reference
        CfnOutput(
            self,
            "CertificateArn",
            value=self.certificate.certificate_arn,
            description="ACM certificate ARN for CloudFront",
            export_name=f"{construct_id}-CertificateArn",
        )
