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

#TODO