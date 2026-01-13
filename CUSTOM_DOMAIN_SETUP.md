# Custom Domain Setup Guide

This guide explains how to configure the custom domain `tdz.kingstonwheelers.cc` for the CloudFront distribution.

## Overview

The infrastructure has been updated to:

- Create an ACM certificate for `tdz.kingstonwheelers.cc` (automatically in us-east-1 for CloudFront)
- Configure CloudFront to use the custom domain
- Enable HTTPS with automatic certificate validation

## Deployment Steps

### 1. Deploy the Updated CDK Stack

Deploy the updated infrastructure:

```bash
cd infrastructure
AWS_PROFILE=personal cdk deploy KwccTdzProdDataStack
```

**Important**: During deployment, CDK will create an ACM certificate and show validation records. Note these down - you'll need them for Cloudflare DNS configuration.

The output will include something like:

```
Certificate validation records:
  Name: _abc123.tdz.kingstonwheelers.cc
  Type: CNAME
  Value: _xyz456.acm-validations.aws.
```

### 2. Configure Cloudflare DNS

Once the deployment completes, you need to add two DNS records in Cloudflare:

#### A. Certificate Validation Record (CNAME)

Add the validation CNAME record shown in the CDK deployment output:

1. Log in to Cloudflare dashboard
2. Navigate to kingstonwheelers.cc domain
3. Go to DNS settings
4. Add a new CNAME record:
   - **Type**: CNAME
   - **Name**: `_abc123.tdz.kingstonwheelers.cc` (from CDK output)
   - **Target**: `_xyz456.acm-validations.aws.` (from CDK output)
   - **Proxy status**: DNS only (grey cloud)
   - **TTL**: Auto

#### B. Website CNAME Record

Add a CNAME pointing to the CloudFront distribution:

1. Get the CloudFront domain name from CDK output: `DistributionDomainName`
2. In Cloudflare DNS settings, add:
   - **Type**: CNAME
   - **Name**: `tdz`
   - **Target**: `<CloudFront-domain>.cloudfront.net` (e.g., `d111111abcdef8.cloudfront.net`)
   - **Proxy status**: DNS only (grey cloud) - **Important: Must be grey cloud for ACM validation**
   - **TTL**: Auto

**Note**: Keep the proxy status as "DNS only" (grey cloud) for ACM certificate validation to work. You can optionally enable Cloudflare proxy (orange cloud) after the certificate is validated, but this is not recommended as it will double-proxy (Cloudflare + CloudFront).

### 3. Verify Certificate Validation

After adding the DNS records, AWS ACM will automatically validate the certificate. This usually takes 5-30 minutes.

You can check the certificate status:

```bash
AWS_PROFILE=personal aws acm list-certificates --region us-east-1 \
  --certificate-statuses ISSUED PENDING_VALIDATION
```

Look for the certificate with domain `tdz.kingstonwheelers.cc`.

### 4. Test the Website

Once the certificate is validated (status: ISSUED), test the website:

```bash
# Test DNS resolution
dig tdz.kingstonwheelers.cc

# Test HTTPS access
curl -I https://tdz.kingstonwheelers.cc
```

The website should be accessible at `https://tdz.kingstonwheelers.cc`.

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
