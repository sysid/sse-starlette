# SSE-Starlette Examples

This directory contains comprehensive examples demonstrating various Server-Sent Events (SSE) patterns and use cases with sse-starlette.

## Quick Start

1. Install dependencies:
```bash
pip install sse-starlette fastapi uvicorn sqlalchemy aiosqlite
```

2. Run any example:
```bash
python 01_basic_sse.py
```

3. Test with curl or use the HTML client (`05_html_client.html`)

## Examples Overview

### 01_basic_sse.py - Basic SSE Streaming
**Purpose**: Introduction to SSE with both Starlette and FastAPI implementations.

**Features**:
- Simple number streaming
- Client disconnection handling
- Both framework implementations in one file

**Usage**:
```bash
python 01_basic_sse.py

# Test endpoints
curl -N http://localhost:8000/starlette/numbers     # Numbers 1-10
curl -N http://localhost:8000/fastapi/endless       # Endless stream
curl -N http://localhost:8000/fastapi/range/5/15    # Custom range
```

### 02_message_broadcasting.py - Real-time Message Broadcasting
**Purpose**: Demonstrates queue-based message broadcasting to multiple clients.

**Features**:
- asyncio.Queue-based broadcasting
- Multiple simultaneous clients
- REST API for sending messages
- Client connection management

**Usage**:
```bash
python 02_message_broadcasting.py

# Subscribe to messages (terminal 1)
curl -N http://localhost:8000/events

# Send messages (terminal 2)
curl -X POST "http://localhost:8000/send" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello World"}'

curl -X POST "http://localhost:8000/send" \
  -H "Content-Type: application/json" \
  -d '{"message": "Alert!", "event": "alert"}'

# Check status
curl http://localhost:8000/status
```

### 03_database_streaming.py - Database Integration
**Purpose**: Shows thread-safe database streaming patterns with SQLAlchemy.

**Features**:
- Thread-safe session management
- Database query result streaming
- Filtering and pagination
- Both correct and incorrect patterns (educational)

**Usage**:
```bash
python 03_database_streaming.py

# Stream all tasks
curl -N http://localhost:8000/tasks/stream

# Filter by completion status
curl -N http://localhost:8000/tasks/stream?completed=true
curl -N http://localhost:8000/tasks/stream?completed=false

# Limit results
curl -N http://localhost:8000/tasks/stream?limit=2

# Get task count
curl http://localhost:8000/tasks/count
```

### 04_advanced_features.py - Advanced SSE Features
**Purpose**: Demonstrates advanced SSE capabilities and configuration options.

**Features**:
- Custom ping messages and intervals
- Error handling within streams
- Send timeout protection
- Custom line separators
- Proxy-friendly headers
- Background tasks

**Usage**:
```bash
python 04_advanced_features.py

# Custom ping every 3 seconds
curl -N http://localhost:8000/custom-ping

# Error handling demonstration
curl -N http://localhost:8000/error-demo

# Send timeout protection
curl -N http://localhost:8000/timeout-protected

# Custom line separators (LF instead of CRLF)
curl -N http://localhost:8000/custom-separator

# Proxy-optimized headers
curl -N http://localhost:8000/proxy-friendly

# Health check
curl http://localhost:8000/health
```

### 05_html_client.html - Complete HTML Client
**Purpose**: Full-featured web client for testing and demonstrating SSE functionality.

**Features**:
- Connection management UI
- Real-time message display
- Message broadcasting capability
- Statistics and monitoring
- Multiple event type handling
- Auto-reconnection support

**Usage**:
1. Start any of the server examples
2. Open `05_html_client.html` in a web browser
3. Enter the SSE endpoint URL
4. Click "Connect" to start receiving events
5. Use the message form to send broadcasts (works with example 02)

## Common Testing Patterns

### Basic Connection Test
```bash
# Test if server is responding
curl -I http://localhost:8000/health

# Basic SSE connection
curl -N http://localhost:8000/events
```

### Multiple Client Simulation
```bash
# Terminal 1
curl -N http://localhost:8000/events &

# Terminal 2
curl -N http://localhost:8000/events &

# Terminal 3 - send messages
curl -X POST "http://localhost:8000/send" \
  -H "Content-Type: application/json" \
  -d '{"message": "Broadcasting to all clients"}'
```

### Error Condition Testing
```bash
# Start stream and interrupt (Ctrl+C) to test cleanup
curl -N http://localhost:8000/endless

# Test with invalid URLs
curl -N http://localhost:8000/nonexistent
```

## Best Practices Demonstrated

### Thread Safety
- ✅ Create database sessions within generators
- ❌ Don't reuse sessions across task boundaries
- ✅ Use proper async context managers

### Error Handling
- Handle client disconnections gracefully
- Implement proper cleanup in finally blocks
- Use asyncio.CancelledError for cancellation
- Provide meaningful error events to clients

### Performance
- Use appropriate ping intervals
- Implement send timeouts for hanging connections
- Consider proxy caching headers for fan-out scenarios
- Monitor client connection counts

### Security
- Validate input data
- Implement proper CORS if needed
- Consider authentication for broadcast endpoints
- Rate limit message sending if necessary

## Architecture Patterns

### Producer-Consumer (Example 02)
```python
# Producer adds messages to queue
await broadcaster.broadcast_message(message)

# Consumer reads from queue and streams to client
message = await client_queue.get()
yield message
```

### Database Streaming (Example 03)
```python
# Always create sessions within generators
async def stream_data():
    async with AsyncSessionLocal() as session:  # ✅ Correct
        # Query and stream data
```

### Event-Driven (Example 04)
```python
# Handle different event types
yield {"data": "content", "event": "custom_type", "id": "unique_id"}
```

## Troubleshooting

### Common Issues

1. **Connection hangs**: Check if server is running and accessible
2. **No messages received**: Verify endpoint URL and server logs
3. **Memory leaks**: Ensure proper client cleanup in finally blocks
4. **Thread safety errors**: Don't reuse database sessions across tasks

### Debug Commands
```bash
# Check server logs
python example.py 2>&1 | grep -E "(ERROR|WARNING|INFO)"

# Test connection with verbose output
curl -v -N http://localhost:8000/events

# Monitor active connections
lsof -i :8000
```

## Production Considerations

### Deployment
- Use proper ASGI servers (uvicorn, gunicorn)
- Configure appropriate worker counts
- Set up proper logging and monitoring
- Implement health checks

### Scaling
- Consider message brokers (Redis, RabbitMQ) for multi-instance setups
- Implement connection pooling for databases
- Use load balancers with sticky sessions if needed
- Monitor memory usage and connection counts

### Security
- Implement authentication and authorization
- Use HTTPS in production
- Configure CORS appropriately
- Rate limit connections and messages

---

For more information, see the main [README.md](../README.md) and the [official documentation](https://github.com/sysid/sse-starlette).
