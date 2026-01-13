# Custom Domain Setup Guide

✅ **Setup Status**: COMPLETE - Website is live at `https://tdz.kingstonwheelers.cc`

This guide documents the custom domain configuration for the CloudFront distribution.

## Completed Configuration

The infrastructure has been successfully deployed with:

- ✅ ACM certificate created and validated for `tdz.kingstonwheelers.cc` in us-east-1
- ✅ CloudFront distribution configured with custom domain
- ✅ Cross-region references between us-east-1 (certificate) and eu-west-1 (CloudFront)
- ✅ DNS records configured in Cloudflare
- ✅ Website accessible at `https://tdz.kingstonwheelers.cc`

## Current Infrastructure Details

- **Certificate ARN**: `arn:aws:acm:us-east-1:002681522526:certificate/89567d7c-a746-4a7c-9446-48ce6028bdb3`
- **Certificate Status**: ISSUED (validated on 2026-01-13)
- **CloudFront Distribution ID**: `E2M7BDO7EQ2UY6`
- **CloudFront Domain**: `d32eiotfjzq7jj.cloudfront.net`
- **Custom Domain**: `tdz.kingstonwheelers.cc`

## Architecture

The setup uses a multi-region architecture:

- **us-east-1**: ACM certificate (required by CloudFront)
- **eu-west-1**: CloudFront distribution, S3 buckets, Lambda functions
- **Cross-region references**: CDK manages certificate ARN sharing between regions

## Cloudflare DNS Configuration

The following DNS records were configured in Cloudflare for the `kingstonwheelers.cc` domain:

### Certificate Validation Record

```
Type:   CNAME
Name:   _2345c15efb5c8c690542496c8584e164.tdz.kingstonwheelers.cc
Target: _93c3f0aac5b5d674f42413343efe3521.jkddzztszm.acm-validations.aws.
Proxy:  DNS only (grey cloud)
TTL:    Auto
```

**Purpose**: ACM certificate DNS validation. This record proves domain ownership to AWS Certificate Manager.

### Website CNAME Record

```
Type:   CNAME
Name:   tdz
Target: d32eiotfjzq7jj.cloudfront.net
Proxy:  DNS only (grey cloud)
TTL:    Auto
```

**Purpose**: Routes traffic from `tdz.kingstonwheelers.cc` to the CloudFront distribution.

**Important**: The proxy status must be "DNS only" (grey cloud), not "Proxied" (orange cloud), to avoid double-CDN overhead (Cloudflare + CloudFront).

## Deployment Process (For Reference)

The deployment was completed in the following order:

### 1. IAM Role Updates

Updated GitHub Actions IAM role to support cross-region deployments:
- Added CDK bootstrap permissions for us-east-1
- Added CloudFormation permissions for us-east-1
- Added S3 CDK assets permissions for us-east-1
- Added ACM Certificate Manager permissions for us-east-1

### 2. CDK Stack Deployment

Deployed three stacks in sequence:

1. **KwccTdzProdCertificateStack** (us-east-1)
   - ACM certificate creation
   - Cross-region export writer for certificate ARN
   - Waited for DNS validation (~8 minutes after DNS records added)

2. **KwccTdzProdDataStack** (eu-west-1)
   - S3 buckets for data and website
   - CloudFront distribution with custom domain
   - Cross-region export reader to import certificate ARN
   - Secrets Manager for ZwiftPower credentials

3. **KwccTdzProdComputeStack** (eu-west-1)
   - Lambda functions for data fetching and processing
   - EventBridge rules for scheduled execution

### 3. DNS Configuration

Added DNS records in Cloudflare in two stages:
1. Certificate validation record (triggered certificate issuance)
2. Website CNAME record (enabled custom domain access)

Total deployment time: ~40 minutes (including certificate validation wait time)

## Verification

The website is now accessible at `https://tdz.kingstonwheelers.cc` with:

- ✅ Valid SSL/TLS certificate (issued by AWS Certificate Manager)
- ✅ CloudFront CDN for global content delivery
- ✅ HTTPS-only access (HTTP redirects to HTTPS)
- ✅ Custom error pages for 403/404 errors

## Troubleshooting

### Certificate Stuck in PENDING_VALIDATION

If the certificate remains in PENDING_VALIDATION status:

1. Verify the CNAME validation record exists in Cloudflare DNS
2. Check the record name and value match exactly (including the trailing dot)
3. Ensure proxy status is "DNS only" (grey cloud)
4. Wait up to 30 minutes for validation to complete
5. Check CloudWatch Logs for any certificate validation errors

### Website Not Accessible

If the website doesn't load:

1. Verify the CNAME record points to the correct CloudFront domain
2. Check that proxy status is "DNS only" (grey cloud)
3. Test the CloudFront domain directly: `https://<distribution-domain>.cloudfront.net`
4. Check CloudFront distribution status (must be "Deployed")
5. Verify the certificate status is "ISSUED"

### Getting CDK Outputs

If you need to retrieve the CDK outputs again:

```bash
cd infrastructure
AWS_PROFILE=personal aws cloudformation describe-stacks \
  --region eu-west-1 \
  --stack-name KwccTdzProdDataStack \
  --query 'Stacks[0].Outputs'
```

## Cloudflare Proxy Status (Orange Cloud vs Grey Cloud)

**Recommendation**: Keep the proxy status as "DNS only" (grey cloud)

- **Grey cloud (DNS only)**: Traffic goes directly to CloudFront
  - Required for ACM certificate validation
  - Simpler architecture (single CDN)
  - CloudFront provides CDN, caching, and SSL

- **Orange cloud (Proxied)**: Traffic goes through Cloudflare, then to CloudFront
  - Double CDN overhead (not recommended)
  - May cause certificate validation issues
  - Adds complexity and potential latency

## Summary

After following these steps:

- ✅ ACM certificate created and validated for `tdz.kingstonwheelers.cc`
- ✅ CloudFront distribution configured with custom domain
- ✅ DNS records configured in Cloudflare
- ✅ Website accessible at `https://tdz.kingstonwheelers.cc`
