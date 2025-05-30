# demonstrations/production_scenarios/load_simulation.py
"""
DEMONSTRATION: Load Testing with Multiple Concurrent Clients

PURPOSE:
Shows how SSE server behaves under load with many concurrent connections.

KEY LEARNING:
- Resource usage scales with client count
- Memory and connection management is critical
- Performance characteristics of SSE at scale

PATTERN:
Controlled load testing to understand SSE performance limits.
"""

import asyncio
import time
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from sse_starlette import EventSourceResponse


class LoadTestServer:
    """
    SSE server instrumented for load testing.
    Tracks connections, memory usage, and performance metrics.
    """

    def __init__(self):
        self.active_connections = 0
        self.total_connections = 0
        self.events_sent = 0
        self.start_time = time.time()

    def connection_started(self):
        self.active_connections += 1
        self.total_connections += 1
        print(f"📈 Active: {self.active_connections}, Total: {self.total_connections}")

    def connection_ended(self):
        self.active_connections -= 1
        print(f"📉 Active: {self.active_connections}")

    def event_sent(self):
        self.events_sent += 1

    @property
    def stats(self):
        uptime = time.time() - self.start_time
        return {
            "active_connections": self.active_connections,
            "total_connections": self.total_connections,
            "events_sent": self.events_sent,
            "uptime_seconds": uptime,
            "events_per_second": self.events_sent / uptime if uptime > 0 else 0
        }


# Global server instance
server = LoadTestServer()


async def load_test_stream(request: Request):
    """
    Stream optimized for load testing.
    Minimal processing to focus on connection handling.
    """
    connection_id = id(request)
    server.connection_started()

    try:
        # Send events with minimal delay for load testing
        for i in range(10):  # Limited events per connection
            if await request.is_disconnected():
                break

            yield {"data": f"Event {i}", "id": str(i)}
            server.event_sent()
            await asyncio.sleep(0.1)  # Fast events for load testing

    finally:
        server.connection_ended()


async def sse_endpoint(request: Request):
    return EventSourceResponse(load_test_stream(request))


async def stats_endpoint(request: Request):
    from starlette.responses import JSONResponse
    return JSONResponse(server.stats)


# Test application
app = Starlette(routes=[
    Route("/events", sse_endpoint),
    Route("/stats", stats_endpoint)
])


class LoadTestClient:
    """
    Client that simulates realistic SSE usage patterns.
    """

    def __init__(self, client_id, base_url):
        self.client_id = client_id
        self.base_url = base_url
        self.events_received = 0
        self.start_time = None
        self.end_time = None

    async def run(self):
        """Run the client simulation."""
        self.start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("GET", f"{self.base_url}/events") as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            self.events_received += 1

                            # Simulate client processing time
                            await asyncio.sleep(0.01)

        except Exception as e:
            print(f"❌ Client {self.client_id} error: {type(e).__name__}")

        finally:
            self.end_time = time.time()

    @property
    def duration(self):
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0


async def run_load_test(num_clients=10, base_url="http://localhost:8000"):
    """
    Run load test with specified number of concurrent clients.
    """
    print(f"🚀 Starting load test with {num_clients} clients...")

    # Create client tasks
    clients = [LoadTestClient(i, base_url) for i in range(num_clients)]
    client_tasks = [client.run() for client in clients]

    # Track progress
    async def progress_monitor():
        for _ in range(10):  # Monitor for 10 seconds
            await asyncio.sleep(1)

            # Get server stats
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.get(f"{base_url}/stats")
                    stats = response.json()
                    print(f"📊 Active: {stats['active_connections']}, "
                          f"Events/sec: {stats['events_per_second']:.1f}")
                except:
                    pass

    # Run load test
    start_time = time.time()
    await asyncio.gather(
        *client_tasks,
        progress_monitor(),
        return_exceptions=True
    )

    # Analyze results
    total_duration = time.time() - start_time
    successful_clients = [c for c in clients if c.events_received > 0]

    print(f"\n📈 Load Test Results:")
    print(f"   Clients: {num_clients}")
    print(f"   Successful: {len(successful_clients)}")
    print(f"   Duration: {total_duration:.1f}s")
    print(f"   Total events: {sum(c.events_received for c in clients)}")
    print(f"   Avg events per client: {sum(c.events_received for c in clients) / len(clients):.1f}")


if __name__ == "__main__":
    """
    DEMONSTRATION STEPS:
    1. Run server: python load_simulation.py (in one terminal)
    2. Run clients: python production_scenarios/load_simulations.py test 20 (in another terminal)
    3. Monitor resource usage with system tools
    4. Experiment with different client counts

    PERFORMANCE INSIGHTS:
    - Memory usage scales linearly with connections
    - CPU usage depends on event frequency
    - Network becomes bottleneck with many clients
    - Connection limits are OS and application dependent
    """
    import uvicorn
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Run as load test client
        num_clients = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        asyncio.run(run_load_test(num_clients))
    else:
        # Run as server
        print("🚀 Starting SSE load test server...")
        print("📋 Run load test with: python load_simulation.py test 20")
        uvicorn.run(app, host="localhost", port=8000, log_level="error")

