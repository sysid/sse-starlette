# demonstrations/production_scenarios/network_interruption.py
"""
DEMONSTRATION: Network Interruption Handling

PURPOSE:
Shows how SSE connections behave during network issues like packet loss,
temporary disconnections, and connection timeouts.

KEY LEARNING:
- Network issues cause immediate SSE connection failures
- Clients must implement reconnection logic
- Server-side timeouts help detect dead connections

PATTERN:
Simulating network conditions to test SSE resilience.
"""

import asyncio
import time
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.middleware.base import BaseHTTPMiddleware
from sse_starlette import EventSourceResponse


class NetworkSimulationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that simulates network conditions.
    """

    def __init__(self, app):
        super().__init__(app)
        self.simulate_delay = False
        self.simulate_failure = False
        self.delay_duration = 2.0

    async def dispatch(self, request, call_next):
        # Simulate network delay
        if self.simulate_delay and request.url.path == "/events":
            print(f"🐌 Simulating {self.delay_duration}s network delay...")
            await asyncio.sleep(self.delay_duration)

        # Simulate network failure
        if self.simulate_failure and request.url.path == "/events":
            print("💥 Simulating network failure!")
            from starlette.responses import Response

            return Response("Network Error", status_code=503)

        return await call_next(request)


# Global middleware instance for control
network_middleware = None


async def robust_stream(request: Request):
    """
    Stream that's designed to handle network issues gracefully.
    """
    connection_id = id(request)
    print(f"🔗 Stream {connection_id} started")

    try:
        for i in range(1, 30):
            # Check for client disconnect frequently
            if await request.is_disconnected():
                print(f"🔌 Client {connection_id} disconnected at event {i}")
                break

            # Send heartbeat and data
            yield {
                "data": f"Event {i} - timestamp: {time.time():.2f}",
                "id": str(i),
                "event": "data",
            }

            # Regular interval - important for detecting dead connections
            await asyncio.sleep(1)

    except Exception as e:
        print(f"💥 Stream {connection_id} error: {e}")
        yield {"data": "Stream error occurred", "event": "error"}
        raise

    finally:
        print(f"🧹 Stream {connection_id} cleanup completed")


async def sse_endpoint(request: Request):
    """SSE endpoint with network resilience."""
    return EventSourceResponse(
        robust_stream(request),
        ping=5,  # Send ping every 5 seconds to detect dead connections
        send_timeout=10.0,  # Timeout sends after 10 seconds
    )


async def control_endpoint(request: Request):
    """Control endpoint to simulate network conditions."""
    from starlette.responses import JSONResponse
    from urllib.parse import parse_qs

    query = parse_qs(str(request.query_params))

    if "delay" in query:
        network_middleware.simulate_delay = query["delay"][0].lower() == "true"
        network_middleware.delay_duration = float(query.get("duration", ["2.0"])[0])

    if "failure" in query:
        network_middleware.simulate_failure = query["failure"][0].lower() == "true"

    return JSONResponse(
        {
            "network_delay": network_middleware.simulate_delay,
            "delay_duration": network_middleware.delay_duration,
            "network_failure": network_middleware.simulate_failure,
        }
    )


# Create app with network simulation
app = Starlette(
    routes=[Route("/events", sse_endpoint), Route("/control", control_endpoint)]
)

# Add network simulation middleware
network_middleware = NetworkSimulationMiddleware(app)
app = network_middleware


class ResilientSSEClient:
    """
    Client with automatic reconnection and error handling.
    Demonstrates production-ready SSE client patterns.
    """

    def __init__(self, base_url, max_retries=3):
        self.base_url = base_url
        self.max_retries = max_retries
        self.events_received = 0
        self.connection_attempts = 0
        self.last_event_id = None

    async def connect_with_retry(self):
        """Connect with exponential backoff retry logic."""

        for attempt in range(self.max_retries + 1):
            self.connection_attempts += 1

            try:
                print(f"🔄 Connection attempt {attempt + 1}/{self.max_retries + 1}")
                await self._connect()
                break  # Success

            except Exception as e:
                print(f"❌ Attempt {attempt + 1} failed: {type(e).__name__}")

                if attempt < self.max_retries:
                    # Exponential backoff: 1s, 2s, 4s, 8s...
                    delay = 2**attempt
                    print(f"⏳ Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    print("💀 All retry attempts exhausted")
                    raise

    async def _connect(self):
        """Single connection attempt."""
        headers = {}

        # Include Last-Event-ID for resumption
        if self.last_event_id:
            headers["Last-Event-ID"] = self.last_event_id
            print(f"📍 Resuming from event ID: {self.last_event_id}")

        async with httpx.AsyncClient(timeout=15.0) as client:
            async with client.stream(
                "GET", f"{self.base_url}/events", headers=headers
            ) as response:
                # Check response status
                if response.status_code != 200:
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}", request=None, response=response
                    )

                print("✅ Connected successfully")

                async for line in response.aiter_lines():
                    if line.strip():
                        self.events_received += 1

                        # Parse event ID for resumption
                        if line.startswith("id: "):
                            self.last_event_id = line[4:]

                        print(f"📨 Event {self.events_received}: {line[:50]}...")

                        # Simulate client processing
                        await asyncio.sleep(0.1)


async def demonstrate_network_issues():
    """
    Demonstrates different network failure scenarios.
    """
    print("🌐 Network Interruption Demonstrations\n")

    client = ResilientSSEClient("http://localhost:8000")

    async def scenario_1_normal_connection():
        """Normal operation baseline."""
        print("📡 Scenario 1: Normal Connection")

        # Reset network conditions
        async with httpx.AsyncClient() as http_client:
            await http_client.get(
                "http://localhost:8000/control?delay=false&failure=false"
            )

        try:
            # Connect for 5 seconds
            await asyncio.wait_for(client.connect_with_retry(), timeout=5.0)
        except asyncio.TimeoutError:
            print("✅ Normal connection worked for 5 seconds")

        print(f"📊 Events received: {client.events_received}\n")

    async def scenario_2_network_delay():
        """Connection with network delays."""
        print("📡 Scenario 2: Network Delays")

        # Enable network delay
        async with httpx.AsyncClient() as http_client:
            await http_client.get(
                "http://localhost:8000/control?delay=true&duration=3.0"
            )

        start_time = time.time()

        try:
            await asyncio.wait_for(client.connect_with_retry(), timeout=10.0)
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            print(f"⏱️  Connection with delays lasted {duration:.1f}s")

        print(f"📊 Additional events: {client.events_received}\n")

    async def scenario_3_connection_failure():
        """Connection failures with retry."""
        print("📡 Scenario 3: Connection Failures")

        # Enable network failures
        async with httpx.AsyncClient() as http_client:
            await http_client.get("http://localhost:8000/control?failure=true")

        try:
            await client.connect_with_retry()
        except Exception as e:
            print(f"💀 Expected failure: {type(e).__name__}")

        # Restore normal operation
        async with httpx.AsyncClient() as http_client:
            await http_client.get("http://localhost:8000/control?failure=false")

        print("🔄 Testing recovery after failure...")
        try:
            await asyncio.wait_for(client.connect_with_retry(), timeout=3.0)
            print("✅ Successfully recovered!")
        except:
            print("❌ Recovery failed")

    # Run scenarios
    await scenario_1_normal_connection()
    await scenario_2_network_delay()
    await scenario_3_connection_failure()

    print(f"📊 Total events received: {client.events_received}")
    print(f"🔄 Total connection attempts: {client.connection_attempts}")


if __name__ == "__main__":
    """
    DEMONSTRATION STEPS:
    1. Start server: python network_interruption.py
    2. Run client test: python -c "import asyncio; from network_interruption import demonstrate_network_issues; asyncio.run(demonstrate_network_issues())"
    3. Observe how client handles different network conditions

    PRODUCTION INSIGHTS:
    - Always implement client-side retry logic
    - Use Last-Event-ID header for stream resumption
    - Set appropriate timeouts on both client and server
    - Monitor connection health with pings
    - Handle partial message delivery gracefully
    """
    import uvicorn
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        # Run client demonstration
        asyncio.run(demonstrate_network_issues())
    else:
        # Run server
        print("🚀 Starting network interruption test server...")
        print("📋 Run demo with: python network_interruption.py demo")
        print(
            "🎛️  Control network: curl 'http://localhost:8000/control?delay=true&duration=5'"
        )
        uvicorn.run(app, host="localhost", port=8000, log_level="error")
