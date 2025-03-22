import argparse

"""
    Entry point for the mcp-ntopng script defined in pyproject.toml. 
    It runs the MCP server with a specific transport protocol.
"""
def main():
    # Parse the command-line arguments to determine the transport protocol.
    parser = argparse.ArgumentParser(description="mcp-ntopng")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
    )
    args = parser.parse_args()

    # Ensure environment variables are loaded before impoting the server
    from mcp_ntopng.mcp_server import mcp

    mcp.run(transport=args.transport)

if __name__ == "__main__":
    main()
