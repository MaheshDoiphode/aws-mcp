# AWS MCP Server

A Model Context Protocol (MCP) server for AWS operations supporting S3, EKS, ECS, EC2, and Cost Explorer.

## Use Cases

### S3 Operations
```
List all S3 buckets using default profile:
- "List my S3 buckets"

List S3 buckets with specific profile and region:
- "List S3 buckets in profile Developer-359712516178 in region ap-southeast-1"
```

### EKS Operations
```
List EKS clusters:
- "List EKS clusters in profile Developer-359712516178"
- "Show all EKS cluster details in ap-southeast-1 region"
```

### ECS Operations
```
List ECS services:
- "List ECS services in default cluster using profile Developer-359712516178"
- "Show services in my-cluster with region ap-southeast-1"

List ECS tasks:
- "List running tasks in my-cluster"
- "Show tasks for service web-app in cluster production"

Describe ECS services:
- "Describe all services in my-cluster using profile Developer-359712516178"
- "Get details for services web-app,api-service in production cluster"
```

### EC2 Operations
```
List EC2 instances:
- "List all running EC2 instances in profile Developer-359712516178"
- "Show stopped instances with tag Environment=staging"
- "List instances i-1234567890abcdef0,i-0987654321fedcba0"

Describe EC2 instances:
- "Describe all EC2 instances with security groups in ap-southeast-1"
- "Get detailed info for instance i-1234567890abcdef0"
```

### Cost and Billing Operations
```
Get cost and usage:
- "Show my AWS costs for the last 30 days using profile Developer-359712516178"
- "Get daily costs grouped by service for the last 7 days"
- "Show EC2 costs for the last month"

Get dimension values:
- "List all AWS services with costs in the last 30 days"
- "Show available regions with usage"

Get rightsizing recommendations:
- "Get EC2 rightsizing recommendations using profile Developer-359712516178"

Get usage forecast:
- "Forecast my AWS costs for the next 30 days"
- "Show monthly cost forecast for the next 3 months"
```

## Profile Configuration

The server works with your existing AWS CLI profiles. Example configuration:

```ini
[profile Developer-359712516178]
sso_session = nonprod-consumer
sso_account_id = 359712516178
sso_role_name = Developer
region = ap-southeast-1
cli_ignore_ssl_verification = true
output = json
```

## Quick Start

1. Ensure AWS CLI is configured with your profiles
2. Run the MCP server: `python aws_mcp_server.py`
3. Use natural language to interact with AWS services

## Notes

- Cost Explorer APIs require appropriate IAM permissions
- SSL verification settings are inherited from AWS CLI config
- All operations support profile and region specification
- Default region: ap-southeast-1 (based on your config)

# vscode settings -
```
"mcp": {
    "servers": {
        "aws-mcp": {
            "type": "stdio",
            "command": "C:\\Users\\P4013673\\AppData\\Local\\Programs\\Python\\Python313\\python.exe",
            "args": [
                "C:\\Users\\P4013673\\AppData\\Roaming\\Roo-Code\\MCP\\aws_s3_mcp_server\\main.py"
            ]
        }
    }
}
```