FROM python:3.13-slim

WORKDIR /app

# Install uv for package management
RUN pip install --no-cache-dir uv

# Install build dependencies and debug tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    curl \
    net-tools \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . /app/

# Install the package in development mode
RUN uv pip install --system --no-cache-dir -e .

# Expose the default ports
EXPOSE 8000
EXPOSE 9000

# Set environment variables with defaults that can be overridden at runtime
ENV NTOPNG_DBUSER=default
ENV NTOPNG_DBPORT=9000      
ENV NTOPNG_SECURE=false     
ENV NTOPNG_VERIFY=true          
ENV NTOPNG_CONNECT_TIMEOUT=30   
ENV NTOPNG_SEND_RECEIVE_TIMEOUT=300 
ENV SELECT_QUERY_TIMEOUT_SECS=30

# Run the server
ENTRYPOINT ["mcp-ntopng"]
#CMD ["--transport", "sse"]
CMD ["--transport", "stdio"]
