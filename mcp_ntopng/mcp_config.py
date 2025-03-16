"""Environment configuration for the MCP ClntopngickHouse server.

This module handles all environment variable configuration with sensible defaults
and type conversion.
"""

from dataclasses import dataclass
import os

@dataclass
class ClickHouseConfig:
    """Configuration for ntopng ClickHouse database connection settings.

    This class handles all environment variable configuration related to
    the ntopng Clickhouse database connection. 

    Required environment variables:
        NTOPNG_HOST: The hostname of the ClickHouse server
        NTOPNG_DBUSER: The username for authentication
        NTOPNG_DBPASSWORD: The password for authentication

    Optional environment variables (with defaults):
        NTOPNG_DBPORT: The port number (default: 8443 if secure=True, 8123 if secure=False)
        NTOPNG_SECURE: Enable HTTPS (default: true)
        NTOPNG_VERIFY: Verify SSL certificates (default: true)
        NTOPNG_CONNECT_TIMEOUT: Connection timeout in seconds (default: 30)
        NTOPNG_SEND_RECEIVE_TIMEOUT: Send/receive timeout in seconds (default: 300)
    """

    def __init__(self):
        """Initialize the configuration from environment variables."""
        self._validate_required_vars()

    @property
    def host(self) -> str:
        """Get the ntopng host."""
        return os.environ["NTOPNG_HOST"]

    @property
    def port(self) -> int:
        """Get the ClickHouse port.

        Defaults to 9440 if secure=True, 9000 if secure=False.
        Can be overridden by CLICKHOUSE_PORT environment variable.
        """
        if "NTOPNG_DBPORT" in os.environ:
            return int(os.environ["NTOPNG_DBPORT"])
        return 9440 if self.secure else 9000

    @property
    def user(self) -> str:
        """Get the ClickHouse user."""
        return os.environ["NTOPNG_DBUSER"]

    @property
    def password(self) -> str:
        """Get the ClickHouse password."""
        return os.environ["NTOPNG_DBPASSWORD"]

    @property
    def database(self) -> str:
        """Get the default database name if set."""
        return "ntopng" 

    @property
    def secure(self) -> bool:
        """Get whether HTTPS is enabled.

        Default: False
        """
        return os.getenv("NTOPNG_SECURE", "false").lower() == "true"

    @property
    def verify(self) -> bool:
        """Get whether SSL certificate verification is enabled.

        Default: True
        """
        return os.getenv("NTOPNG_VERIFY", "true").lower() == "true"

    @property
    def connect_timeout(self) -> int:
        """Get the connection timeout in seconds.

        Default: 30
        """
        return int(os.getenv("NTOPNG_CONNECT_TIMEOUT", "30"))

    @property
    def send_receive_timeout(self) -> int:
        """Get the send/receive timeout in seconds.

        Default: 300 (ClickHouse default)
        """
        return int(os.getenv("NTOPNG_SEND_RECEIVE_TIMEOUT", "300"))

    def get_client_config(self) -> dict:
        """Get the configuration dictionary for clickhouse_connect client.

        Returns:
            dict: Configuration ready to be passed to clickhouse_connect.get_client()
        """
        config = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "secure": self.secure,
            "verify": self.verify,
            "connect_timeout": self.connect_timeout,
            "send_receive_timeout": self.send_receive_timeout,
            "database": "ntopng",
            "client_name": "mcp_ntopng",
        }

        return config

    def _validate_required_vars(self) -> None:
        """Validate that all required environment variables are set.

        Raises:
            ValueError: If any required environment variable is missing.
        """
        missing_vars = []
        for var in ["NTOPNG_HOST", "NTOPNG_DBUSER", "NTOPNG_DBPASSWORD"]:
            if var not in os.environ:
                missing_vars.append(var)

        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )


# Global instance for easy access
config = ClickHouseConfig()
