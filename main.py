#!/usr/bin/env python
import json
import sys
import os
import boto3
import configparser
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


class AWSS3MCPServer:
    def __init__(self):
        if MCP_SDK_AVAILABLE:
            self.server = Server("aws-s3-mcp-server")
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
                )
            ]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name != "list_s3_buckets":
                raise McpError(
                    ErrorCode.MethodNotFound,
                    f"Unknown tool: {name}",
                )

            profile_name = arguments.get("profile_name")
            region_name = arguments.get("region_name")

            try:
                session_params = {}
                if profile_name:
                    session_params["profile_name"] = profile_name
                if region_name:
                    session_params["region_name"] = region_name
                
                session = boto3.Session(**session_params)
                
                # Check SSL verification setting
                verify_ssl = self._check_ssl_verification(profile_name)
                
                # Create S3 client with SSL verification setting
                s3_client = session.client("s3", verify=verify_ssl)
                
                if not verify_ssl:
                    # Suppress SSL warnings when verification is disabled
                    import urllib3
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

    async def _handle_call_tool_mock(self, request):
        """Mock version for when MCP SDK is not available"""
        if hasattr(request, 'params'):
            name = request.params.name
            args = request.params.arguments or {}
        else:
            # Direct call format
            name = request.name if hasattr(request, 'name') else 'list_s3_buckets'
            args = request.arguments if hasattr(request, 'arguments') else {}

        if name != "list_s3_buckets":
            raise McpError(
                ErrorCode.MethodNotFound,
                f"Unknown tool: {name}",
            )

        profile_name = args.get("profile_name")
        region_name = args.get("region_name")

        try:
            session_params = {}
            if profile_name:
                session_params["profile_name"] = profile_name
            if region_name:
                session_params["region_name"] = region_name
            
            session = boto3.Session(**session_params)
            
            # Check SSL verification setting
            verify_ssl = self._check_ssl_verification(profile_name)
            
            # Create S3 client with SSL verification setting
            s3_client = session.client("s3", verify=verify_ssl)
            
            if not verify_ssl:
                # Suppress SSL warnings when verification is disabled
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                print(f"SSL verification disabled for profile: {profile_name or 'default'}", file=sys.stderr)

            response = s3_client.list_buckets()
            buckets = [bucket["Name"] for bucket in response.get("Buckets", [])]
            return {"content": [{"type": "text", "text": json.dumps(buckets, indent=2)}]}

        except (NoCredentialsError, PartialCredentialsError) as e:
            error_message = f"AWS credentials not found or incomplete. Ensure AWS CLI is configured. Profile: {profile_name or 'default'}. Error: {str(e)}"
            return {"content": [{"type": "text", "text": error_message}], "isError": True}
        except ClientError as e:
            error_message = f"AWS ClientError: {e.response.get('Error', {}).get('Code', 'Unknown')} - {e.response.get('Error', {}).get('Message', 'No message')}. Profile: {profile_name or 'default'}."
            if "SSL: CERTIFICATE_VERIFY_FAILED" in str(e):
                error_message += " SSL verification failed. Check if 'cli_ignore_ssl_verification = true' is set in your AWS config for the profile, or if a custom CA bundle is needed via AWS_CA_BUNDLE."
            return {"content": [{"type": "text", "text": error_message}], "isError": True}
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}. Profile: {profile_name or 'default'}."
            return {"content": [{"type": "text", "text": error_message}], "isError": True}

    async def run(self):
        if not MCP_SDK_AVAILABLE or self.server is None:
            print("MCP SDK not available. Cannot start server. Run 'pip install mcp' if you want to use it as a server.", file=sys.stderr)
            # Fallback to direct execution for testing if SDK is not present
            if len(sys.argv) > 1 and sys.argv[1] == "test_list_buckets":
                profile_to_test = sys.argv[2] if len(sys.argv) > 2 else None
                region_to_test = sys.argv[3] if len(sys.argv) > 3 else None
                print(f"Testing list_s3_buckets with profile: {profile_to_test}, region: {region_to_test}", file=sys.stderr)
                mock_request = type('obj', (object,), {
                    'name': 'list_s3_buckets',
                    'arguments': {'profile_name': profile_to_test, 'region_name': region_to_test}
                })
                try:
                    result = await self._handle_call_tool_mock(mock_request)
                    print(f"Result: {result['content'][0]['text']}", file=sys.stdout)
                except McpError as e:
                    print(f"Error: {e}", file=sys.stderr)
            return

        try:
            # Run the stdio server
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options()
                )
        except Exception as e:
            print(f"CRITICAL: MCP server failed to start: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    # Ensure asyncio event loop is available for Python versions < 3.7 on Windows
    if sys.platform == "win32" and sys.version_info < (3, 8):
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    print("Attempting to start AWSS3MCPServer instance...", file=sys.stderr)
    server_instance = AWSS3MCPServer()
    
    import asyncio
    try:
        if MCP_SDK_AVAILABLE:
            print("MCP SDK available, attempting to run server...", file=sys.stderr)
        else:
            print("Running in test mode...", file=sys.stderr)
        asyncio.run(server_instance.run())
    except Exception as e_main:
        print(f"CRITICAL: Server execution failed: {e_main}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)