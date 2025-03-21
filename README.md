# mcp-server-ntopng
[![PyPI - Version](https://img.shields.io/pypi/v/mcp-ntopng)](https://pypi.org/project/mcp-ntopng)

NTOPNG Model Context Protocol Server

<a href="https://glama.ai/mcp/servers/@marcoeg/mcp-server-ntopng">
<img width="380" height="200" src="https://glama.ai/mcp/servers/@marcoeg/mcp-server-ntopng/badge" />

A [Model Context Protocol](https://modelcontextprotocol.io/) server implementation for [NTOPNG](https://www.ntop.org/products/traffic-analysis/ntop/) that enables AI agents to query networks monitoring data using the NTOPNG database.

This MCP Server assumes that `ntopng` is using ClickHouse to store historical flows and alert. Check [ntopng Clickhouse](https://www.ntop.org/guides/ntopng/flow_dump/clickhouse/index.html)


## Tools

* `fetch_ntopng_all_ifids`
- Retrieve all available interface IDs from ntopng.
* `get_ntopng_hosts_location`
- Fetch geographical location and additional info for hosts.
* `fetch_ntopng_top_local_talkers`
- Retrieve the top 10 local talkers for a specified interface.
* `fetch_ntopng_top_remote_talkers`
- Retrieve the top 10 remote talkers for a specified interface.
* `get_ntopng_all_alert_stats`
- Retrieve statistics for all alerts.
* `get_ntopng_flow_alert_stats`
- Retrieve statistics for flow alerts.
* `get_ntopng_host_alert_stats`
- Retrieve statistics for host alerts.
* `get_ntopng_interface_alert_stats`
- Retrieve statistics for interface alerts.
* `get_ntopng_mac_alert_stats`
- Retrieve statistics for MAC alerts.
* `get_ntopng_network_alert_stats`
- Retrieve statistics for network alerts.
* `get_ntopng_snmp_device_alert_list`
- Retrieve a list of SNMP device alerts.
* `get_ntopng_snmp_device_alert_stats`
- Retrieve statistics for SNMP device alerts.
* `get_ntopng_system_alert_stats`
- Retrieve statistics for system alerts.
* `query_ntopng_flows_data`
- Retrieve detailed flows data from the ntopng flows database.
* `get_ntopng_top-k_flows`
- Retrieve top-k flows data from the ntopng flows database.
* `get_ntopng_user_alert_stats`
- Retrieve statistics for user alerts.
* `get_ntopng_flow_devices_stats`
- Retrieve statistics for all flow dev`ices.
* `get_ntopng_sflow_devices_stats`
- Retrieve statistics for all sFlow devices.
* `list_tables_ntopng_database`
- List tables structure of the ntopng database.
* `query_ntopng_database`
- Query the ntopng Clickhouse database.

## Status

Works with Claude Desktop app and other MCP compliant hosts and clients. 

No support for MCP [resources](https://modelcontextprotocol.io/docs/concepts/resources) or [prompts](https://modelcontextprotocol.io/docs/concepts/prompts) yet.

## Configuration

1. Create or edit the Claude Desktop configuration file located at:
   - On macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

2. Add the following:

```json
{
  "mcpServers": {
    "mcp-ntopng": {
      "command": "/path/to/your/uv-binary",
      "args": ["run", "--with", "mcp-ntopng", "--python", "3.13", "mcp-ntopng"]
      "env": {
        "NTOPNG_HOST": "<ntopng-host>",
        "NTOPNG_DBPORT": "<ntopng-dbport>",
        "NTOPNG_DBUSER": "<ntopng-dbuser>",
        "NTOPNG_DBPASSWORD": "<ntopng-dbpassword>",
        "NTOPNG_SECURE": "true",
        "NTOPNG_VERIFY": "true",
        "NTOPNG_CONNECT_TIMEOUT": "30",
        "NTOPNG_SEND_RECEIVE_TIMEOUT": "300",
        "NTOPNG_API_KEY": "NTOPNG_TOKEN"
      }
    }
  }
}
```


3. Replace `/path/to/your/uv-binary` with the absolute path to the `uv` executable. Find the path with `which uv`. This ensures that the correct version of `uv` is used when starting the server.

4. Restart Claude Desktop to apply the changes.


## Development 

1. Set the environmental variables either in the `claude_desktop_config.json` file or in a `.env` file in the root of the repository.

```
NTOPNG_HOST=localhost
NTOPNG_PORT=9000
NTOPNG_USER=default
NTOPNG_PASSWORD=
```

3. Run `uv sync` to install the dependencies. To install `uv` follow the instructions [here](https://docs.astral.sh/uv/). Then do `source .venv/bin/activate`.

4. Install the `mcp-ntopng` package with `uv pip install -e .` from the project main directory. 

4. For easy testing, you can run `mcp dev mcp_ntopng/mcp_server.py` to start the MCP server. **CHANGE WITH A PROPER CHAT CLIENT**

### Environment Variables

The following environment variables are used to configure the database connection:

* `NTOPNG_HOST`: The hostname of the `ntopng` server
* `NTOPNG_DBUSER`: The username for Clickhouse DB authentication
* `NTOPNG_DBPASSWORD`: The password for Clickhouse DB authentication
* `NTOPNG_API_KEY`: The `ntopng` authentication token.

#### Optional
* `NTOPNG_DBPORT`: The port number of the Clickhouse DB in the  `ntopng` server
  - Default: `9000` if HTTPS is enabled, `8123` if disabled
  - Usually doesn't need to be set unless using a non-standard port
* `NTOPNG_SECURE`: Enable/disable a TLS connection
  - Default: `false`
  - Set to `true` for a secure TLS connections
* `NTOPNG_VERIFY`: Enable/disable SSL certificate verification
  - Default: `true`
  - Set to `false to disable certificate verification (not recommended for production)
* `NTOPNG_CONNECT_TIMEOUT`: Connection timeout in seconds
  - Default: `30
  - Increase this value if you experience connection timeouts
* `NTOPNG_SEND_RECEIVE_TIMEOUT`: Send/receive timeout in seconds
  - Default: `300`
  - Increase this value for long-running queries


> Check [TLS Setup](https://www.ntop.org/guides/ntopng/flow_dump/clickhouse/clickhouse.html#tls-connection) in the `ntopng` documentation for details about setting up a TLS connection to Clickhouse.

### Development
Install the package on the local machine:
```
$ uv sync
$ uv pip install -e .
```
Run the MCP Inspector
```
$ cd mcp_ntopng
$ source .env
$ CLIENT_PORT=8077 SERVER_PORT=8078  mcp dev run_mcp_ntopng.py --with clickhouse-driver --with python-dotenv --with uvicorn --with pip-system-certs
```
Use the local library in Claude Desktop.

Find:  /Users/marco/Library/Application\ Support/Claude/claude_desktop_config.json 

Edit the claude_desktop_config.json changing the local paths:
```
{
    "mcpServers": {
      "mcp-ntopng": {
        "command": "/Users/marco/Development/claude/mcp-server-ntopng/.venv/bin/python",
        "args": [
           "/Users/marco/Development/claude/mcp-server-ntopng/run_mcp_ntopng.py"
        ],
        "env": {
          "NTOPNG_HOST": "marcoeg-nod004.ntoplink.com",
          "NTOPNG_DBPORT": "9000",
          "NTOPNG_DBUSER": "default",
          "NTOPNG_DBPASSWORD": "",
          "NTOPNG_SECURE": "false",
          "NTOPNG_VERIFY": "false",
          "NTOPNG_CONNECT_TIMEOUT": "30",
          "NTOPNG_SEND_RECEIVE_TIMEOUT": "300",
          "SELECT_QUERY_TIMEOUT_SECS": "30",
          "NTOPNG_API_KEY": "NTOPNG_TOKEN"
        }
      }
    }
  }
  ```
