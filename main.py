#!/usr/bin/env python
import json
import sys
import os
import boto3
import configparser
from datetime import datetime, timedelta
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

# Try to import MCP components
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        CallToolRequest,
        ListToolsRequest,
        Tool,
        TextContent,
        CallToolResult,
        ListToolsResult,
    )
    # Import error types from the correct location
    from mcp import McpError
    # Error codes are available as constants in types module
    from mcp.types import INVALID_REQUEST, INVALID_PARAMS, INTERNAL_ERROR, METHOD_NOT_FOUND
    
    # Create ErrorCode class for compatibility
    class ErrorCode:
        InvalidRequest = INVALID_REQUEST
        MethodNotFound = METHOD_NOT_FOUND
        InternalError = INTERNAL_ERROR
        InvalidParams = INVALID_PARAMS
    
    MCP_SDK_AVAILABLE = True
    print("MCP SDK found and imported successfully.", file=sys.stderr)
except ImportError as e:
    MCP_SDK_AVAILABLE = False
    print(f"MCP SDK not found: {e}. Running in mock mode.", file=sys.stderr)
    
    # Mock classes if SDK is not available for basic testing of the core logic
    class McpError(Exception):
        def __init__(self, code, message):
            super().__init__(message)
            self.code = code
    
    class ErrorCode:
        InvalidRequest = "InvalidRequest"
        MethodNotFound = "MethodNotFound"
        InternalError = "InternalError"
        InvalidParams = "InvalidParams"

    CallToolRequest = None
    ListToolsRequest = None
    Server = None
    stdio_server = None


class AWSMCPServer:
    def __init__(self):
        if MCP_SDK_AVAILABLE:
            self.server = Server("aws-mcp-server")
            self._setup_tool_handlers()
        else:
            self.server = None # Mock server

    def _check_ssl_verification(self, profile_name=None):
        """Check if SSL verification should be disabled based on AWS config"""
        try:
            # Get AWS config file path
            aws_config_path = os.path.expanduser("~/.aws/config")
            
            if not os.path.exists(aws_config_path):
                return True  # Default to verify SSL if no config
            
            config = configparser.ConfigParser()
            config.read(aws_config_path)
            
            # Check the specific profile or default
            section_name = f"profile {profile_name}" if profile_name and profile_name != "default" else "default"
            
            if section_name in config:
                ssl_verify = config.get(section_name, "cli_ignore_ssl_verification", fallback="false")
                return ssl_verify.lower() != "true"
            
            return True  # Default to verify SSL
        except Exception as e:
            print(f"Warning: Could not read AWS config for SSL settings: {e}", file=sys.stderr)
            return True

    def _setup_tool_handlers(self):
        if not MCP_SDK_AVAILABLE or self.server is None:
            return

        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                # S3 Tools
                Tool(
                    name="list_s3_buckets",
                    description="Lists S3 buckets using the configured AWS profile. Optionally takes a profile name.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use. If not provided, the default profile is used.",
                            },
                            "region_name": {
                                "type": "string",
                                "description": "The AWS region to use. If not provided, the default configured region for the profile is used.",
                            }
                        },
                        "required": [],
                    },
                ),
                # EKS Tools
                Tool(
                    name="list_eks_clusters",
                    description="Lists EKS clusters using the configured AWS profile. Optionally takes a profile name and region.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use. If not provided, the default profile is used.",
                            },
                            "region_name": {
                                "type": "string",
                                "description": "The AWS region to use. If not provided, the default configured region for the profile is used.",
                            },
                            "include_all": {
                                "type": "boolean",
                                "description": "Include all cluster details (equivalent to --include all flag). Default is false.",
                                "default": False
                            }
                        },
                        "required": [],
                    },
                ),
                # ECS Tools
                Tool(
                    name="list_ecs_services",
                    description="Lists ECS services in a cluster.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cluster_name": {
                                "type": "string",
                                "description": "The ECS cluster name or ARN. If not provided, lists services from the default cluster.",
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            },
                            "region_name": {
                                "type": "string",
                                "description": "The AWS region to use.",
                            }
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="list_ecs_tasks",
                    description="Lists ECS tasks in a cluster, optionally filtered by service.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cluster_name": {
                                "type": "string",
                                "description": "The ECS cluster name or ARN.",
                            },
                            "service_name": {
                                "type": "string",
                                "description": "Filter tasks by service name.",
                            },
                            "desired_status": {
                                "type": "string",
                                "description": "Filter by task status (RUNNING, PENDING, STOPPED).",
                                "enum": ["RUNNING", "PENDING", "STOPPED"]
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            },
                            "region_name": {
                                "type": "string",
                                "description": "The AWS region to use.",
                            }
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="describe_ecs_services",
                    description="Describes ECS services with detailed information.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "cluster_name": {
                                "type": "string",
                                "description": "The ECS cluster name or ARN.",
                            },
                            "service_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of service names to describe. If not provided, describes all services in the cluster.",
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            },
                            "region_name": {
                                "type": "string",
                                "description": "The AWS region to use.",
                            }
                        },
                        "required": [],
                    },
                ),
                # EC2 Tools
                Tool(
                    name="list_ec2_instances",
                    description="Lists EC2 instances with basic information.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "instance_states": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Filter by instance states (running, stopped, pending, etc.).",
                            },
                            "instance_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Specific instance IDs to list.",
                            },
                            "tag_filters": {
                                "type": "object",
                                "description": "Filter by tags (key-value pairs).",
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            },
                            "region_name": {
                                "type": "string",
                                "description": "The AWS region to use.",
                            }
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="describe_ec2_instances",
                    description="Describes EC2 instances with detailed information.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "instance_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Specific instance IDs to describe. If not provided, describes all instances.",
                            },
                            "include_security_groups": {
                                "type": "boolean",
                                "description": "Include security group details.",
                                "default": False
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            },
                            "region_name": {
                                "type": "string",
                                "description": "The AWS region to use.",
                            }
                        },
                        "required": [],
                    },
                ),
                # Cost and Billing Tools
                Tool(
                    name="get_cost_and_usage",
                    description="Gets cost and usage data for a specified time period and granularity.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "time_period_days": {
                                "type": "integer",
                                "description": "Number of days back to retrieve cost data (default: 30).",
                                "default": 30
                            },
                            "granularity": {
                                "type": "string",
                                "description": "Time granularity for cost data.",
                                "enum": ["DAILY", "MONTHLY"],
                                "default": "DAILY"
                            },
                            "group_by": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Group costs by dimensions (SERVICE, REGION, INSTANCE_TYPE, etc.).",
                            },
                            "filter_service": {
                                "type": "string",
                                "description": "Filter costs by specific AWS service.",
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            }
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="get_dimension_values",
                    description="Gets available dimension values for cost filtering (services, regions, etc.).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "dimension": {
                                "type": "string",
                                "description": "The dimension to get values for.",
                                "enum": ["SERVICE", "REGION", "INSTANCE_TYPE", "LINKED_ACCOUNT", "OPERATION", "USAGE_TYPE"]
                            },
                            "time_period_days": {
                                "type": "integer",
                                "description": "Number of days back to search for dimension values (default: 30).",
                                "default": 30
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            }
                        },
                        "required": ["dimension"],
                    },
                ),
                Tool(
                    name="get_rightsizing_recommendations",
                    description="Gets EC2 rightsizing recommendations to optimize costs.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "AWS service for recommendations.",
                                "enum": ["EC2-Instance"],
                                "default": "EC2-Instance"
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            }
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="get_usage_forecast",
                    description="Gets usage forecast for AWS services.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "time_period_days": {
                                "type": "integer",
                                "description": "Number of days to forecast (default: 30).",
                                "default": 30
                            },
                            "metric": {
                                "type": "string",
                                "description": "Metric to forecast.",
                                "enum": ["BLENDED_COST", "UNBLENDED_COST", "AMORTIZED_COST", "NET_AMORTIZED_COST", "NET_UNBLENDED_COST"],
                                "default": "BLENDED_COST"
                            },
                            "granularity": {
                                "type": "string",
                                "description": "Time granularity for forecast.",
                                "enum": ["DAILY", "MONTHLY"],
                                "default": "DAILY"
                            },
                            "profile_name": {
                                "type": "string",
                                "description": "The AWS CLI profile name to use.",
                            }
                        },
                        "required": [],
                    },
                ),
            ]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
            # Original tools
            if name == "list_s3_buckets":
                return await self._handle_s3_list_buckets(arguments)
            elif name == "list_eks_clusters":
                return await self._handle_eks_list_clusters(arguments)
            # ECS tools
            elif name == "list_ecs_services":
                return await self._handle_ecs_list_services(arguments)
            elif name == "list_ecs_tasks":
                return await self._handle_ecs_list_tasks(arguments)
            elif name == "describe_ecs_services":
                return await self._handle_ecs_describe_services(arguments)
            # EC2 tools
            elif name == "list_ec2_instances":
                return await self._handle_ec2_list_instances(arguments)
            elif name == "describe_ec2_instances":
                return await self._handle_ec2_describe_instances(arguments)
            # Cost and billing tools
            elif name == "get_cost_and_usage":
                return await self._handle_get_cost_and_usage(arguments)
            elif name == "get_dimension_values":
                return await self._handle_get_dimension_values(arguments)
            elif name == "get_rightsizing_recommendations":
                return await self._handle_get_rightsizing_recommendations(arguments)
            elif name == "get_usage_forecast":
                return await self._handle_get_usage_forecast(arguments)
            else:
                raise McpError(
                    ErrorCode.MethodNotFound,
                    f"Unknown tool: {name}",
                )

    # Core AWS client creation method
    def _create_aws_client(self, service_name: str, profile_name: str = None, region_name: str = None):
        """Create AWS client with proper SSL and session configuration"""
        session_params = {}
        if profile_name:
            session_params["profile_name"] = profile_name
        if region_name:
            session_params["region_name"] = region_name
        
        session = boto3.Session(**session_params)
        
        # Check SSL verification setting
        verify_ssl = self._check_ssl_verification(profile_name)
        
        # Create client with SSL verification setting
        client = session.client(service_name, verify=verify_ssl)
        
        if not verify_ssl:
            # Suppress SSL warnings when verification is disabled
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        return client

    # Original S3 and EKS handlers (unchanged)
    async def _handle_s3_list_buckets(self, arguments: dict) -> list[TextContent]:
        """Handle S3 bucket listing"""
        profile_name = arguments.get("profile_name")
        region_name = arguments.get("region_name")

        try:
            s3_client = self._create_aws_client("s3", profile_name, region_name)
            response = s3_client.list_buckets()
            buckets = [bucket["Name"] for bucket in response.get("Buckets", [])]
            
            result_text = json.dumps(buckets, indent=2)
            return [TextContent(type="text", text=result_text)]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Ensure AWS CLI is configured. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            if "SSL: CERTIFICATE_VERIFY_FAILED" in str(e):
                error_message += " SSL verification failed. Check if 'cli_ignore_ssl_verification = true' is set in your AWS config for the profile, or if a custom CA bundle is needed via AWS_CA_BUNDLE."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def _handle_eks_list_clusters(self, arguments: dict) -> list[TextContent]:
        """Handle EKS cluster listing"""
        profile_name = arguments.get("profile_name")
        region_name = arguments.get("region_name")
        include_all = arguments.get("include_all", False)

        try:
            eks_client = self._create_aws_client("eks", profile_name, region_name)

            # List clusters
            response = eks_client.list_clusters()
            clusters = response.get("clusters", [])
            
            if include_all and clusters:
                # Get detailed information for each cluster
                cluster_details = []
                for cluster_name in clusters:
                    try:
                        cluster_info = eks_client.describe_cluster(name=cluster_name)
                        cluster_details.append(cluster_info["cluster"])
                    except ClientError as e:
                        # If we can't describe a cluster, include basic info with error
                        cluster_details.append({
                            "name": cluster_name,
                            "error": f"Could not describe cluster: {e.response.get('Error', {}).get('Message', 'Unknown error')}"
                        })
                
                result_text = json.dumps(cluster_details, indent=2, default=str)
            else:
                # Just return cluster names (similar to your working command)
                result_text = json.dumps({"clusters": clusters}, indent=2)
            
            return [TextContent(type="text", text=result_text)]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Ensure AWS CLI is configured. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            if "SSL: CERTIFICATE_VERIFY_FAILED" in str(e):
                error_message += " SSL verification failed. Check if 'cli_ignore_ssl_verification = true' is set in your AWS config for the profile, or if a custom CA bundle is needed via AWS_CA_BUNDLE."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    # New ECS handlers
    async def _handle_ecs_list_services(self, arguments: dict) -> list[TextContent]:
        """Handle ECS service listing"""
        cluster_name = arguments.get("cluster_name", "default")
        profile_name = arguments.get("profile_name")
        region_name = arguments.get("region_name")

        try:
            ecs_client = self._create_aws_client("ecs", profile_name, region_name)
            
            response = ecs_client.list_services(cluster=cluster_name)
            services = response.get("serviceArns", [])
            
            # Extract service names from ARNs for readability
            service_names = []
            for service_arn in services:
                service_name = service_arn.split("/")[-1] if "/" in service_arn else service_arn
                service_names.append(service_name)
            
            result = {
                "cluster": cluster_name,
                "services": service_names,
                "service_arns": services
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Cluster: {cluster_name}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Cluster: {cluster_name}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def _handle_ecs_list_tasks(self, arguments: dict) -> list[TextContent]:
        """Handle ECS task listing"""
        cluster_name = arguments.get("cluster_name", "default")
        service_name = arguments.get("service_name")
        desired_status = arguments.get("desired_status")
        profile_name = arguments.get("profile_name")
        region_name = arguments.get("region_name")

        try:
            ecs_client = self._create_aws_client("ecs", profile_name, region_name)
            
            list_params = {"cluster": cluster_name}
            if service_name:
                list_params["serviceName"] = service_name
            if desired_status:
                list_params["desiredStatus"] = desired_status
            
            response = ecs_client.list_tasks(**list_params)
            task_arns = response.get("taskArns", [])
            
            result = {
                "cluster": cluster_name,
                "service": service_name,
                "desired_status": desired_status,
                "task_count": len(task_arns),
                "task_arns": task_arns
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Cluster: {cluster_name}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Cluster: {cluster_name}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def _handle_ecs_describe_services(self, arguments: dict) -> list[TextContent]:
        """Handle ECS service description"""
        cluster_name = arguments.get("cluster_name", "default")
        service_names = arguments.get("service_names")
        profile_name = arguments.get("profile_name")
        region_name = arguments.get("region_name")

        try:
            ecs_client = self._create_aws_client("ecs", profile_name, region_name)
            
            # If no specific services provided, get all services first
            if not service_names:
                list_response = ecs_client.list_services(cluster=cluster_name)
                service_arns = list_response.get("serviceArns", [])
                if not service_arns:
                    return [TextContent(type="text", text=json.dumps({"cluster": cluster_name, "services": []}, indent=2))]
                service_names = [arn.split("/")[-1] for arn in service_arns]
            
            # Describe services (max 10 at a time due to AWS API limits)
            all_services = []
            for i in range(0, len(service_names), 10):
                batch = service_names[i:i+10]
                response = ecs_client.describe_services(
                    cluster=cluster_name,
                    services=batch
                )
                all_services.extend(response.get("services", []))
            
            result = {
                "cluster": cluster_name,
                "services": all_services
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Cluster: {cluster_name}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Cluster: {cluster_name}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    # New EC2 handlers
    async def _handle_ec2_list_instances(self, arguments: dict) -> list[TextContent]:
        """Handle EC2 instance listing"""
        instance_states = arguments.get("instance_states", [])
        instance_ids = arguments.get("instance_ids", [])
        tag_filters = arguments.get("tag_filters", {})
        profile_name = arguments.get("profile_name")
        region_name = arguments.get("region_name")

        try:
            ec2_client = self._create_aws_client("ec2", profile_name, region_name)
            
            # Build filters
            filters = []
            if instance_states:
                filters.append({
                    "Name": "instance-state-name",
                    "Values": instance_states
                })
            
            for tag_key, tag_value in tag_filters.items():
                filters.append({
                    "Name": f"tag:{tag_key}",
                    "Values": [tag_value] if isinstance(tag_value, str) else tag_value
                })
            
            describe_params = {}
            if instance_ids:
                describe_params["InstanceIds"] = instance_ids
            if filters:
                describe_params["Filters"] = filters
            
            response = ec2_client.describe_instances(**describe_params)
            
            # Extract instance information
            instances = []
            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    instance_info = {
                        "InstanceId": instance.get("InstanceId"),
                        "InstanceType": instance.get("InstanceType"),
                        "State": instance.get("State", {}).get("Name"),
                        "PublicIpAddress": instance.get("PublicIpAddress"),
                        "PrivateIpAddress": instance.get("PrivateIpAddress"),
                        "LaunchTime": instance.get("LaunchTime"),
                        "Tags": {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                    }
                    instances.append(instance_info)
            
            result = {
                "instance_count": len(instances),
                "instances": instances
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def _handle_ec2_describe_instances(self, arguments: dict) -> list[TextContent]:
        """Handle EC2 instance detailed description"""
        instance_ids = arguments.get("instance_ids", [])
        include_security_groups = arguments.get("include_security_groups", False)
        profile_name = arguments.get("profile_name")
        region_name = arguments.get("region_name")

        try:
            ec2_client = self._create_aws_client("ec2", profile_name, region_name)
            
            describe_params = {}
            if instance_ids:
                describe_params["InstanceIds"] = instance_ids
            
            response = ec2_client.describe_instances(**describe_params)
            
            # Extract detailed instance information
            instances = []
            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    instance_info = {
                        "InstanceId": instance.get("InstanceId"),
                        "InstanceType": instance.get("InstanceType"),
                        "State": instance.get("State", {}),
                        "PublicIpAddress": instance.get("PublicIpAddress"),
                        "PrivateIpAddress": instance.get("PrivateIpAddress"),
                        "PublicDnsName": instance.get("PublicDnsName"),
                        "PrivateDnsName": instance.get("PrivateDnsName"),
                        "LaunchTime": instance.get("LaunchTime"),
                        "Platform": instance.get("Platform"),
                        "Architecture": instance.get("Architecture"),
                        "ImageId": instance.get("ImageId"),
                        "KeyName": instance.get("KeyName"),
                        "VpcId": instance.get("VpcId"),
                        "SubnetId": instance.get("SubnetId"),
                        "Monitoring": instance.get("Monitoring", {}),
                        "Tags": {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                    }
                    
                    if include_security_groups:
                        instance_info["SecurityGroups"] = instance.get("SecurityGroups", [])
                    
                    instances.append(instance_info)
            
            result = {
                "instance_count": len(instances),
                "instances": instances
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    # Cost and Billing handlers
    async def _handle_get_cost_and_usage(self, arguments: dict) -> list[TextContent]:
        """Handle cost and usage data retrieval"""
        time_period_days = arguments.get("time_period_days", 30)
        granularity = arguments.get("granularity", "DAILY")
        group_by = arguments.get("group_by", [])
        filter_service = arguments.get("filter_service")
        profile_name = arguments.get("profile_name")

        try:
            # Cost Explorer is only available in us-east-1
            ce_client = self._create_aws_client("ce", profile_name, "us-east-1")
            
            # Calculate time period
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=time_period_days)
            
            # Build request parameters
            params = {
                "TimePeriod": {
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d")
                },
                "Granularity": granularity,
                "Metrics": ["BlendedCost", "UnblendedCost", "UsageQuantity"]
            }
            
            # Add grouping if specified
            if group_by:
                params["GroupBy"] = [{"Type": "DIMENSION", "Key": dim} for dim in group_by]
            
            # Add service filter if specified
            if filter_service:
                params["Filter"] = {
                    "Dimensions": {
                        "Key": "SERVICE",
                        "Values": [filter_service]
                    }
                }
            
            response = ce_client.get_cost_and_usage(**params)
            
            result = {
                "time_period": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                },
                "granularity": granularity,
                "group_by": group_by,
                "filter_service": filter_service,
                "results": response.get("ResultsByTime", [])
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            if "AccessDenied" in str(e):
                error_message += " Note: Cost Explorer API requires appropriate IAM permissions."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def _handle_get_dimension_values(self, arguments: dict) -> list[TextContent]:
        """Handle dimension values retrieval for cost filtering"""
        dimension = arguments.get("dimension")
        time_period_days = arguments.get("time_period_days", 30)
        profile_name = arguments.get("profile_name")

        try:
            # Cost Explorer is only available in us-east-1
            ce_client = self._create_aws_client("ce", profile_name, "us-east-1")
            
            # Calculate time period
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=time_period_days)
            
            response = ce_client.get_dimension_values(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d")
                },
                Dimension=dimension
            )
            
            dimension_values = [item["Value"] for item in response.get("DimensionValues", [])]
            
            result = {
                "dimension": dimension,
                "time_period": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                },
                "values": dimension_values,
                "total_count": len(dimension_values)
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            if "AccessDenied" in str(e):
                error_message += " Note: Cost Explorer API requires appropriate IAM permissions."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def _handle_get_rightsizing_recommendations(self, arguments: dict) -> list[TextContent]:
        """Handle rightsizing recommendations retrieval"""
        service = arguments.get("service", "EC2-Instance")
        profile_name = arguments.get("profile_name")

        try:
            # Cost Explorer is only available in us-east-1
            ce_client = self._create_aws_client("ce", profile_name, "us-east-1")
            
            response = ce_client.get_rightsizing_recommendation(Service=service)
            
            result = {
                "service": service,
                "recommendations": response.get("RightsizingRecommendations", []),
                "summary": response.get("Summary", {}),
                "configuration": response.get("Configuration", {})
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            if "AccessDenied" in str(e):
                error_message += " Note: Cost Explorer API requires appropriate IAM permissions."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def _handle_get_usage_forecast(self, arguments: dict) -> list[TextContent]:
        """Handle usage forecast retrieval"""
        time_period_days = arguments.get("time_period_days", 30)
        metric = arguments.get("metric", "BLENDED_COST")
        granularity = arguments.get("granularity", "DAILY")
        profile_name = arguments.get("profile_name")

        try:
            # Cost Explorer is only available in us-east-1
            ce_client = self._create_aws_client("ce", profile_name, "us-east-1")
            
            # Calculate time period for forecast (starts from today)
            start_date = datetime.now().date()
            end_date = start_date + timedelta(days=time_period_days)
            
            response = ce_client.get_cost_forecast(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d")
                },
                Metric=metric,
                Granularity=granularity
            )
            
            result = {
                "metric": metric,
                "granularity": granularity,
                "time_period": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                },
                "total": response.get("Total", {}),
                "forecast_results": response.get("ForecastResultsByTime", [])
            }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return [TextContent(type="text", text=error_message)]
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            if "AccessDenied" in str(e):
                error_message += " Note: Cost Explorer API requires appropriate IAM permissions."
            return [TextContent(type="text", text=error_message)]
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return [TextContent(type="text", text=error_message)]

    async def run(self):
        """Run the MCP server"""
        if not MCP_SDK_AVAILABLE:
            print("MCP SDK not available. Cannot run server.", file=sys.stderr)
            return
        
        print("Starting AWS MCP Server...", file=sys.stderr)
        async with stdio_server() as streams:
            await self.server.run(
                streams[0], streams[1], self.server.create_initialization_options()
            )


def main():
    """Main entry point"""
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # Test mode - just verify imports and basic functionality
        print("AWS MCP Server - Test Mode", file=sys.stderr)
        print(f"MCP SDK Available: {MCP_SDK_AVAILABLE}", file=sys.stderr)
        
        server = AWSMCPServer()
        if server.server:
            print("Server initialized successfully", file=sys.stderr)
        else:
            print("Server in mock mode", file=sys.stderr)
        
        return
    
    # Normal server mode
    import asyncio
    server = AWSMCPServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()