import logging
import concurrent.futures
import atexit
import datetime

from clickhouse_driver import Client
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
from mcp_ntopng.mcp_config import config

import os
import requests
from typing import Dict, Any, List, Sequence

NTOPNG_HOST = os.getenv("NTOPNG_HOST")
if not NTOPNG_HOST:
    raise ValueError("NTOPNG_HOST environment variable not set")
BASE_URL = f"https://{NTOPNG_HOST}"

# Retrieve the API key from an environment variable
NTOPNG_API_KEY = os.getenv("NTOPNG_API_KEY")
if not NTOPNG_API_KEY:
    raise ValueError("NTOPNG_API_KEY environment variable not set")

# Headers for authentication
HEADERS = {
    "Authorization": f"Token {NTOPNG_API_KEY}",
    "Content-Type": "application/json"
}

MCP_SERVER_NAME = "mcp-ntopng"

# Basic logging
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(MCP_SERVER_NAME)

# Global settings for query execution
QUERY_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10)
SELECT_QUERY_TIMEOUT_SECS = 30
# Wait for the pending queries to return at exit
atexit.register(lambda: QUERY_EXECUTOR.shutdown(wait=True))

deps = [
    "clickhouse-driver",
    "python-dotenv",
    "uvicorn",
    "pip-system-certs",
    "requests"
]

mcp = FastMCP(MCP_SERVER_NAME, dependencies=deps)

######################################################
#    ntopng Clickhouse database access
######################################################

def create_clickhouse_client():
    """
    Creates and validates a connection to the ClickHouse database.
    
    Retrieves connection parameters from config, establishes a connection,
    and verifies it by checking the server version.
    
    Returns:
        Client: A configured and tested ClickHouse client instance
        
    Raises:
        ConnectionError: When connection cannot be established
        ConfigurationError: When configuration is invalid
    """
    # Get configuration from the global config instance
    client_config = config.get_client_config()
    
    logger.info(
        f"Creating ClickHouse client connection to {client_config['host']}:{client_config['port']} "
        f"as {client_config['user']} "
        f"(secure={client_config['secure']}, verify={client_config['verify']}, "
        f"connect_timeout={client_config['connect_timeout']}s, "
        f"send_receive_timeout={client_config['send_receive_timeout']}s, "
        f"database={client_config['database']})"
    )
    
    try:
        # Establish connection to ClickHouse using clickhouse_driver.Client
        client = Client(**client_config)
        
        # Test connection by querying server version
        #version = client.execute("SELECT version()")[0][0]
        #logger.info(f"Successfully connected to ClickHouse server version {version}")
        
        return client
        
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Failed to connect to ClickHouse: {str(e)}", exc_info=True)
        raise ConnectionError(f"Unable to connect to ClickHouse: {str(e)}")

def execute_query(query: str):
    """
    Executes a ClickHouse query and returns structured results optimized for LLM function calling.
    
    Args:
        query (str): The SQL query to execute
    
    Returns:
        dict: A dictionary containing:
            - status (str): "success" or "error"
            - data (list): List of row dictionaries (on success)
            - metadata (dict): Information about the query results (on success)
            - error (str): Error message (on error)
    """
    import datetime
    client = create_clickhouse_client()
    
    # Create a response structure optimized for LLM consumption
    response = {
        "status": "success",
        "data": [],
        "metadata": {},
        "error": None
    }
    
    try:
        # Execute the query directly
        result = client.execute(query, with_column_types=True)
        
        # clickhouse-driver returns (data, column_types) when with_column_types=True
        rows = result[0]
        column_types = result[1]
        column_names = [col[0] for col in column_types]
        
        # Process result rows into dictionaries
        data_rows = []
        for row in rows:
            row_dict = {}
            for i, col_name in enumerate(column_names):
                row_dict[col_name] = row[i]
            data_rows.append(row_dict)
        
        # Add data and metadata to response
        response["data"] = data_rows
        response["metadata"] = {
            "row_count": len(data_rows),
            "column_names": column_names,
            "column_types": [col[1] for col in column_types],
            "query_time": datetime.datetime.now().isoformat(),
            "query": query,
        }
        
        logger.info(f"Query returned {len(data_rows)} rows")
        
    except Exception as err:
        # Consistent error handling with detailed information
        error_message = str(err)
        logger.error(f"Error executing query: {error_message}")
        
        # Update response for error case
        response["status"] = "error"
        response["error"] = error_message
        response["data"] = []  # Ensure empty data on error
    
    return response

from .ntopng_schema import NTOPNG_SCHEMA
@mcp.tool("list_tables_ntopng_database", description="List tables structure of the ntopng database")
def list_tables():
    logger.info("Returning predefined table schemas for 'ntopng'")

    return NTOPNG_SCHEMA

@mcp.tool(name="query_ntopng_database", description="Query the ntopng Clickhouse database.")
def query_ntopngdb(query: str):
    """
    Executes a query against the ntopng database with timeout protection.
    
    Args:
        query (str): SQL query to execute
        
    Returns:
        dict: Response object with status, data, and error information
    """
    # Log query for debugging and audit purposes
    logger.info(f"Executing query: {query}")
    
    # Enforce SELECT query for security (prevent modification operations)
    if not query.strip().upper().startswith("SELECT"):
        return {
            "status": "error",
            "error": "Only SELECT queries are permitted",
            "data": [],
            "metadata": {"query": query}
        }
    
    # Submit query to thread pool
    future = QUERY_EXECUTOR.submit(execute_query, query)
    
    try:
        # Wait for result with timeout
        result = future.result(timeout=SELECT_QUERY_TIMEOUT_SECS)
        return result
        
    except concurrent.futures.TimeoutError:
        # Handle query timeout
        logger.warning(f"Query timed out after {SELECT_QUERY_TIMEOUT_SECS} seconds: {query}")
        
        # Attempt to cancel the running query (may not work depending on database driver)
        future.cancel()
        
        # Return a standardized error response
        return {
            "status": "error",
            "error": f"Query timeout after {SELECT_QUERY_TIMEOUT_SECS} seconds",
            "data": [],
            "metadata": {
                "query": query,
                "timeout_seconds": SELECT_QUERY_TIMEOUT_SECS
            }
        }
    
    except Exception as e:
        # Catch any other exceptions that might occur
        logger.error(f"Unexpected error executing query: {str(e)}")
        return {
            "status": "error",
            "error": f"Unexpected error: {str(e)}",
            "data": [],
            "metadata": {"query": query}
        }


######################################################
#    ntopng API
######################################################

# Function to fetch all ifid values - validated
@mcp.tool(name="fetch_ntopng_all_ifids", description="Retrieve all available interface IDs from ntopng.")
def get_all_ifids() -> List[int]:
    """
    Retrieve all available interface IDs (ifid) from ntopng.

    Returns:
        List[int]: A list of all ifid values.

    Raises:
        requests.RequestException: If the API call fails.
        KeyError: If the response JSON structure is unexpected.
    """
    url = f"{BASE_URL}/lua/rest/v2/get/ntopng/interfaces.lua"
    response = requests.get(url, headers=HEADERS, verify=True)
    response.raise_for_status()
    data = response.json()
    if data["rc"] != 0:
        raise ValueError(f"API error: {data['rc_str']}")
    # Assuming rsp is a list of dicts with 'ifid' keys
    ifid_list = [interface["ifid"] for interface in data["rsp"]]
    return ifid_list

# --- Hosts Section --- 
#
# Find hosts geographical locations -- not ok: returns empty object
@mcp.tool(name="get_ntopng_hosts_location", description="Fetch geographical location and additional info for hosts.")
def get_hosts_location(ifid: int) -> Dict[str, Any]:
    """
    Fetch the location and additional information of hosts.

    Args:
        ifid (int): Interface identifier.

    Returns:
        Dict[str, Any]: JSON response with host location data.

    Raises:
        requests.RequestException: If the API request encounters an error.
    """
    url = f"{BASE_URL}/lua/rest/v2/get/geo_map/hosts.lua"
    params = {"ifid": ifid}
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Find the local top talkers: ok but it is the pro version
@mcp.tool(name="fetch_ntopng_top_local_talkers", description="Retrieve the top 10 local talkers for a specified interface.")
def get_top_local_talkers(ifid: int) -> Dict[str, Any]:
    """
    Get the top 10 local talkers for a specified interface.

    Args:
        ifid (int): Interface ID.

    Returns:
        Dict[str, Any]: JSON response with top local talkers data.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/interface/top/local/talkers.lua"
    params = {"ifid": ifid}
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Find the remote top talkers: ok but it is the pro version
@mcp.tool(name="fetch_ntopng_top_remote_talkers", description="Retrieve the top 10 remote talkers for a specified interface.")
def get_top_remote_talkers(ifid: int) -> Dict[str, Any]:
    """
    Get the top 10 remote talkers for a specified interface.

    Args:
        ifid (int): Interface ID.

    Returns:
        Dict[str, Any]: JSON response with top remote talkers data.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/interface/top/remote/talkers.lua"
    params = {"ifid": ifid}
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# --- Alerts Section ---
# Get stats on alert categories. not ok: both pro and non-pro paths return empty objects
@mcp.tool(name="get_ntopng_all_alert_stats", description="Retrieve statistics for all alerts.")
def get_all_alert_stats(ifid: int, epoch_begin: int, epoch_end: int) -> Dict[str, Any]:
    """
    Get all alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).

    Returns:
        Dict[str, Any]: JSON response with alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/all/alert/top.lua"
    params = {"ifid": ifid, "epoch_begin": epoch_begin, "epoch_end": epoch_end}
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats on flow alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_flow_alert_stats", description="Retrieve statistics for flow alerts.")
def get_flow_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, score: str, 
                         ip_version: str, ip: str, cli_ip: str, srv_ip: str, cli_name: str, srv_name: str, 
                         cli_port: str, srv_port: str, vlan_id: str, l7proto: str, cli_country: str, 
                         srv_country: str, probe_ip: str, input_snmp: str, output_snmp: str, snmp_interface: str, 
                         cli_host_pool_id: str, srv_host_pool_id: str, cli_network: str, srv_network: str, 
                         l7_error_id: str, traffic_direction: str, format: str) -> Dict[str, Any]:
    """
    Get flow alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').
        ip_version (str): IP version filter (e.g., 'id;eq').
        ip (str): IP address filter (e.g., 'id;eq').
        cli_ip (str): Client IP filter (e.g., 'id;eq').
        srv_ip (str): Server IP filter (e.g., 'id;eq').
        cli_name (str): Client hostname filter (e.g., 'id;eq').
        srv_name (str): Server hostname filter (e.g., 'id;eq').
        cli_port (str): Client port filter (e.g., 'id;eq').
        srv_port (str): Server port filter (e.g., 'id;eq').
        vlan_id (str): VLAN ID filter (e.g., 'id;eq').
        l7proto (str): Application protocol filter (e.g., 'id;eq').
        cli_country (str): Client country filter (e.g., 'id;eq').
        srv_country (str): Server country filter (e.g., 'id;eq').
        probe_ip (str): Probe IP filter (e.g., 'id;eq').
        input_snmp (str): Input SNMP interface filter (e.g., 'id;eq').
        output_snmp (str): Output SNMP interface filter (e.g., 'id;eq').
        snmp_interface (str): SNMP interface filter (e.g., 'id;eq').
        cli_host_pool_id (str): Client host pool filter (e.g., 'id;eq').
        srv_host_pool_id (str): Server host pool filter (e.g., 'id;eq').
        cli_network (str): Client network filter (e.g., 'id;eq').
        srv_network (str): Server network filter (e.g., 'id;eq').
        l7_error_id (str): Application layer error filter (e.g., 'id;eq').
        traffic_direction (str): Traffic direction filter (e.g., 'id;eq').
        format (str): Format of return data ('json' or 'txt').

    Returns:
        Dict[str, Any]: JSON response with flow alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/flow/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score,
        "ip_version": ip_version,
        "ip": ip,
        "cli_ip": cli_ip,
        "srv_ip": srv_ip,
        "cli_name": cli_name,
        "srv_name": srv_name,
        "cli_port": cli_port,
        "srv_port": srv_port,
        "vlan_id": vlan_id,
        "l7proto": l7proto,
        "cli_country": cli_country,
        "srv_country": srv_country,
        "probe_ip": probe_ip,
        "input_snmp": input_snmp,
        "output_snmp": output_snmp,
        "snmp_interface": snmp_interface,
        "cli_host_pool_id": cli_host_pool_id,
        "srv_host_pool_id": srv_host_pool_id,
        "cli_network": cli_network,
        "srv_network": srv_network,
        "l7_error_id": l7_error_id,
        "traffic_direction": traffic_direction,
        "format": format
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats on flow alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_host_alert_stats", description="Retrieve statistics for host alerts.")
def get_host_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, score: str, 
                         vlan_id: str, ip_version: str, ip: str, name: str, host_pool_id: str, network: str) -> Dict[str, Any]:
    """
    Get host alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').
        vlan_id (str): VLAN ID filter (e.g., 'id;eq').
        ip_version (str): IP version filter (e.g., 'id;eq').
        ip (str): IP address filter (e.g., 'id;eq').
        name (str): Hostname filter (e.g., 'id;eq').
        host_pool_id (str): Host pool filter (e.g., 'id;eq').
        network (str): Network filter (e.g., 'id;eq').

    Returns:
        Dict[str, Any]: JSON response with host alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/host/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score,
        "vlan_id": vlan_id,
        "ip_version": ip_version,
        "ip": ip,
        "name": name,
        "host_pool_id": host_pool_id,
        "network": network
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats on interface alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_interface_alert_stats", description="Retrieve statistics for interface alerts.")
def get_interface_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, 
                              score: str, subtype: str) -> Dict[str, Any]:
    """
    Get interface alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').
        subtype (str): Alert subtype.

    Returns:
        Dict[str, Any]: JSON response with interface alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/interface/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score,
        "subtype": subtype
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats on mac alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_mac_alert_stats", description="Retrieve statistics for MAC alerts.")
def get_mac_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, score: str) -> Dict[str, Any]:
    """
    Get MAC alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').

    Returns:
        Dict[str, Any]: JSON response with MAC alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/mac/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats on network alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_network_alert_stats", description="Retrieve statistics for network alerts.")
def get_network_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, 
                            score: str, network_name: str) -> Dict[str, Any]:
    """
    Get network alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').
        network_name (str): Network name filter (e.g., 'id;eq').

    Returns:
        Dict[str, Any]: JSON response with network alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/network/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score,
        "network_name": network_name
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get snmo device alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_snmp_device_alert_list", description="Retrieve a list of SNMP device alerts.")
def get_snmp_device_alert_list(ifid: int, start: int, length: int, epoch_begin: int, epoch_end: int, 
                               alert_id: str, severity: str, score: str, ip: str, snmp_interface: str, 
                               format: str) -> Dict[str, Any]:
    """
    Get a list of SNMP device alerts.

    Args:
        ifid (int): Interface identifier.
        start (int): Starting record index (e.g., 100 for 101st record).
        length (int): Maximum number of records to retrieve.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').
        ip (str): IP address filter (e.g., 'id;eq').
        snmp_interface (str): SNMP interface filter (e.g., 'id;eq').
        format (str): Format of return data ('json' or 'txt').

    Returns:
        Dict[str, Any]: JSON response with SNMP device alert list.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/snmp/device/alert/list.lua"
    params = {
        "ifid": ifid,
        "start": start,
        "length": length,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score,
        "ip": ip,
        "snmp_interface": snmp_interface,
        "format": format
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats on snmp device alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_snmp_device_alert_stats", description="Retrieve statistics for SNMP device alerts.")
def get_snmp_device_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, 
                                score: str, ip: str, snmp_interface: str) -> Dict[str, Any]:
    """
    Get SNMP device alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').
        ip (str): IP address filter (e.g., 'id;eq').
        snmp_interface (str): SNMP interface filter (e.g., 'id;eq').

    Returns:
        Dict[str, Any]: JSON response with SNMP device alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/snmp/device/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score,
        "ip": ip,
        "snmp_interface": snmp_interface
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats on system alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_system_alert_stats", description="Retrieve statistics for system alerts.")
def get_system_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, score: str) -> Dict[str, Any]:
    """
    Get system alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').

    Returns:
        Dict[str, Any]: JSON response with system alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/system/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# --- Flows Section ---

# Query flow data. not ok: parameters not clear
@mcp.tool(name="query_ntopng_flows_data", description="Retrieve detailed flows data from the ntopng flows database.")
def get_flows_data(ifid: int, begin_time_clause: int, end_time_clause: int, select_clause: str = "*", 
                   where_clause: str = "", maxhits_clause: int = 10, order_by_clause: str = "", 
                   group_by_clause: str = "") -> Dict[str, Any]:
    """
    Retrieve flows data from the database.

    Args:
        ifid (int): Interface identifier.
        begin_time_clause (int): Start time in epoch format.
        end_time_clause (int): End time in epoch format.
        select_clause (str, optional): SQL SELECT clause (default: "*").
        where_clause (str, optional): SQL WHERE clause (default: none).
        maxhits_clause (int, optional): Maximum number of hits (default: 10).
        order_by_clause (str, optional): SQL ORDER BY clause (default: none).
        group_by_clause (str, optional): SQL GROUP BY clause (default: none).

    Returns:
        Dict[str, Any]: JSON response with flows data.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/db/flows.lua"
    params = {
        "ifid": ifid,
        "begin_time_clause": begin_time_clause,
        "end_time_clause": end_time_clause,
        "select_clause": select_clause,
        "where_clause": where_clause,
        "maxhits_clause": maxhits_clause,
        "order_by_clause": order_by_clause,
        "group_by_clause": group_by_clause
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get top flows data. not ok: parameters not clear
@mcp.tool(name="get_ntopng_top-k_flows", description="Retrieve top-k flows data from the ntopng flows database.")
def get_topk_flows(ifid: int, begin_time_clause: int, end_time_clause: int, select_keys_clause: str = "IPV4_SRC_ADDR,IPV4_DST_ADDR,L7_PROTO", 
                   select_values_clause: str = "BYTES", where_clause: str = "", topk_clause: str = "SUM", 
                   approx_search: str = "true", maxhits_clause: int = 10) -> Dict[str, Any]:
    """
    Retrieve top-k flows data from the database.

    Args:
        ifid (int): Interface identifier.
        begin_time_clause (int): Start time (epoch).
        end_time_clause (int): End time (epoch).
        select_keys_clause (str, optional): Comma-separated keys list (default: 'IPV4_SRC_ADDR,IPV4_DST_ADDR,L7_PROTO').
        select_values_clause (str, optional): Select value (default: 'BYTES').
        where_clause (str, optional): SQL WHERE clause (default: none).
        topk_clause (str, optional): Top-K clause (default: 'SUM').
        approx_search (str, optional): Approximate search (default: 'true').
        maxhits_clause (int, optional): Maximum number of hits (default: 10).

    Returns:
        Dict[str, Any]: JSON response with top-k flows data.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/db/topk_flows.lua"
    params = {
        "ifid": ifid,
        "begin_time_clause": begin_time_clause,
        "end_time_clause": end_time_clause,
        "select_keys_clause": select_keys_clause,
        "select_values_clause": select_values_clause,
        "where_clause": where_clause,
        "topk_clause": topk_clause,
        "approx_search": approx_search,
        "maxhits_clause": maxhits_clause
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats for user alerts. not ok: parameters not clear
@mcp.tool(name="get_ntopng_user_alert_stats", description="Retrieve statistics for user alerts.")
def get_user_alert_stats(ifid: int, epoch_begin: int, epoch_end: int, alert_id: str, severity: str, score: str) -> Dict[str, Any]:
    """
    Get user alert statistics.

    Args:
        ifid (int): Interface identifier.
        epoch_begin (int): Start time (epoch).
        epoch_end (int): End time (epoch).
        alert_id (str): Alert identifier (e.g., 'id;eq').
        severity (str): Severity identifier (e.g., 'id;eq').
        score (str): Score filter (e.g., 'id;eq').

    Returns:
        Dict[str, Any]: JSON response with user alert stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/user/alert/top.lua"
    params = {
        "ifid": ifid,
        "epoch_begin": epoch_begin,
        "epoch_end": epoch_end,
        "alert_id": alert_id,
        "severity": severity,
        "score": score
    }
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats for flow devices. 
@mcp.tool(name="get_ntopng_flow_devices_stats", description="Retrieve statistics for all flow devices.")
def get_flow_devices_stats(ifid: int) -> Dict[str, Any]:
    """
    Get flow devices statistics.

    Args:
        ifid (int): Interface identifier.

    Returns:
        Dict[str, Any]: JSON response with flow devices stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/flowdevices/stats.lua"
    params = {"ifid": ifid}
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()

# Get stats for sflow devices. 
@mcp.tool(name="get_ntopng_sflow_devices_stats", description="Retrieve statistics for all sFlow devices.")
def get_sflow_devices_stats(ifid: int) -> Dict[str, Any]:
    """
    Get sFlow devices statistics.

    Args:
        ifid (int): Interface identifier.

    Returns:
        Dict[str, Any]: JSON response with sFlow devices stats.

    Raises:
        requests.RequestException: If the request fails.
    """
    url = f"{BASE_URL}/lua/pro/rest/v2/get/sflowdevices/stats.lua"
    params = {"ifid": ifid}
    response = requests.get(url, headers=HEADERS, params=params, verify=True)
    response.raise_for_status()
    return response.json()
