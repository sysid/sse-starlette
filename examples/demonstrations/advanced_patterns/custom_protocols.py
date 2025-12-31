# demonstrations/advanced_patterns/custom_protocols.py
"""
DEMONSTRATION: Custom SSE Protocols

PURPOSE:
Shows how to build custom protocols on top of SSE for specialized use cases.

KEY LEARNING:
- SSE can be extended with custom event types and data formats
- Protocol versioning and negotiation
- Building domain-specific streaming APIs

PATTERN:
Layered protocol design using SSE as transport layer.
"""

import asyncio
import json
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, Any, Optional
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from sse_starlette import EventSourceResponse, ServerSentEvent


class TaskStatus(Enum):
    """Task execution states in our custom protocol."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskProgressEvent:
    """
    Custom protocol message for task progress updates.
    This demonstrates structured data over SSE.
    """

    task_id: str
    status: TaskStatus
    progress_percent: int
    message: str
    timestamp: float
    metadata: Optional[Dict[str, Any]] = None

    def to_sse_event(self) -> ServerSentEvent:
        """Convert to SSE event with custom protocol structure."""
        return ServerSentEvent(
            data=json.dumps(asdict(self)),
            event="task_progress",
            id=f"{self.task_id}-{int(self.timestamp)}",
        )


@dataclass
class SystemHealthEvent:
    """Protocol message for system health monitoring."""

    component: str
    status: str
    metrics: Dict[str, float]
    alerts: list[str]
    timestamp: float

    def to_sse_event(self) -> ServerSentEvent:
        return ServerSentEvent(
            data=json.dumps(asdict(self)),
            event="health_update",
            id=f"health-{int(self.timestamp)}",
        )


class CustomProtocolHandler:
    """
    Handles custom protocol logic and message formatting.
    Demonstrates how to build domain-specific APIs over SSE.
    """

    def __init__(self, protocol_version: str = "1.0"):
        self.protocol_version = protocol_version
        self.active_tasks: Dict[str, TaskStatus] = {}
        self.client_capabilities: Dict[str, set] = {}

    def negotiate_protocol(self, request: Request) -> Dict[str, Any]:
        """
        Negotiate protocol capabilities with client.
        Uses HTTP headers for capability exchange.
        """
        client_version = request.headers.get("X-Protocol-Version", "1.0")
        client_features = request.headers.get("X-Client-Features", "").split(",")

        # Store client capabilities
        client_id = str(id(request))
        self.client_capabilities[client_id] = set(
            f.strip() for f in client_features if f.strip()
        )

        return {
            "server_version": self.protocol_version,
            "client_version": client_version,
            "supported_events": [
                "task_progress",
                "health_update",
                "system_alert",
                "protocol_info",
            ],
            "features": ["compression", "batching", "filtering"],
        }

    def supports_feature(self, client_id: str, feature: str) -> bool:
        """Check if client supports a specific feature."""
        return feature in self.client_capabilities.get(client_id, set())

    async def create_protocol_handshake_event(
        self, request: Request
    ) -> ServerSentEvent:
        """
        Create initial handshake event with protocol information.
        This establishes the custom protocol session.
        """
        protocol_info = self.negotiate_protocol(request)

        return ServerSentEvent(
            data=json.dumps(protocol_info), event="protocol_handshake", id="handshake-0"
        )


# Global protocol handler
protocol_handler = CustomProtocolHandler()


async def task_monitoring_protocol(request: Request):
    """
    Custom protocol for task monitoring and progress tracking.
    Demonstrates structured, domain-specific SSE communication.
    """
    client_id = str(id(request))

    # Send protocol handshake
    yield protocol_handler.create_protocol_handshake_event(request)

    # Simulate multiple tasks with different lifecycles
    tasks = [
        {"id": "build-001", "name": "Build Application", "duration": 8},
        {"id": "test-001", "name": "Run Tests", "duration": 5},
        {"id": "deploy-001", "name": "Deploy to Production", "duration": 3},
    ]

    import time

    try:
        for task in tasks:
            task_id = task["id"]
            duration = task["duration"]

            # Task starting
            start_event = TaskProgressEvent(
                task_id=task_id,
                status=TaskStatus.PENDING,
                progress_percent=0,
                message=f"Starting {task['name']}",
                timestamp=time.time(),
            )
            yield start_event.to_sse_event()

            # Task running with progress updates
            for progress in range(0, 101, 20):
                if await request.is_disconnected():
                    return

                status = TaskStatus.RUNNING if progress < 100 else TaskStatus.COMPLETED
                message = f"{task['name']} - {progress}% complete"

                progress_event = TaskProgressEvent(
                    task_id=task_id,
                    status=status,
                    progress_percent=progress,
                    message=message,
                    timestamp=time.time(),
                    metadata={"phase": "execution", "worker": f"worker-{task_id[-1]}"},
                )

                yield progress_event.to_sse_event()
                await asyncio.sleep(duration / 5)  # Spread progress over task duration

            # Brief pause between tasks
            await asyncio.sleep(0.5)

    except Exception as e:
        # Send error in protocol format
        error_event = TaskProgressEvent(
            task_id="system",
            status=TaskStatus.FAILED,
            progress_percent=0,
            message=f"Protocol error: {e}",
            timestamp=time.time(),
        )
        yield error_event.to_sse_event()


async def system_monitoring_protocol(request: Request):
    """
    Custom protocol for system health monitoring.
    Shows how to stream complex structured data.
    """
    import time
    import random

    # Send protocol handshake
    yield protocol_handler.create_protocol_handshake_event(request)

    components = ["database", "cache", "api", "worker"]

    try:
        for cycle in range(20):
            if await request.is_disconnected():
                break

            # Generate health data for each component
            for component in components:
                # Simulate varying health metrics
                cpu_usage = random.uniform(10, 90)
                memory_usage = random.uniform(20, 80)
                response_time = random.uniform(50, 500)

                # Generate alerts based on thresholds
                alerts = []
                if cpu_usage > 80:
                    alerts.append(f"High CPU usage: {cpu_usage:.1f}%")
                if memory_usage > 70:
                    alerts.append(f"High memory usage: {memory_usage:.1f}%")
                if response_time > 300:
                    alerts.append(f"Slow response time: {response_time:.0f}ms")

                status = (
                    "healthy"
                    if not alerts
                    else "warning"
                    if len(alerts) < 2
                    else "critical"
                )

                health_event = SystemHealthEvent(
                    component=component,
                    status=status,
                    metrics={
                        "cpu_usage_percent": cpu_usage,
                        "memory_usage_percent": memory_usage,
                        "response_time_ms": response_time,
                        "uptime_hours": cycle * 0.1,
                    },
                    alerts=alerts,
                    timestamp=time.time(),
                )

                yield health_event.to_sse_event()

            await asyncio.sleep(2)  # Health check interval

    except Exception as e:
        # Send system error
        error_event = SystemHealthEvent(
            component="monitoring",
            status="failed",
            metrics={},
            alerts=[f"Monitoring system error: {e}"],
            timestamp=time.time(),
        )
        yield error_event.to_sse_event()


async def multi_protocol_endpoint(request: Request):
    """
    Endpoint that supports multiple custom protocols based on request parameters.
    Demonstrates protocol selection and routing.
    """
    protocol_type = request.query_params.get("protocol", "task")

    if protocol_type == "task":
        return EventSourceResponse(
            task_monitoring_protocol(request),
            headers={"X-Protocol-Type": "task-monitoring-v1"},
        )
    elif protocol_type == "health":
        return EventSourceResponse(
            system_monitoring_protocol(request),
            headers={"X-Protocol-Type": "health-monitoring-v1"},
        )
    else:
        # Default: Send protocol information
        async def protocol_info():
            yield ServerSentEvent(
                data=json.dumps(
                    {
                        "error": f"Unknown protocol: {protocol_type}",
                        "available_protocols": ["task", "health"],
                        "usage": "Add ?protocol=<type> to URL",
                    }
                ),
                event="protocol_error",
            )

        return EventSourceResponse(protocol_info())


async def compressed_protocol_endpoint(request: Request):
    """
    Demonstrates protocol with data compression and batching.
    Advanced technique for high-throughput scenarios.
    """
    client_id = str(id(request))
    supports_batching = protocol_handler.supports_feature(client_id, "batching")

    async def compressed_stream():
        # Send handshake
        yield protocol_handler.create_protocol_handshake_event(request)

        import time

        batch_buffer = []

        # Generate high-frequency data
        for i in range(100):
            if await request.is_disconnected():
                break

            event_data = {
                "sequence": i,
                "timestamp": time.time(),
                "data": f"High frequency data point {i}",
                "metrics": {"value": i * 1.5, "rate": i / 10.0},
            }

            if supports_batching:
                # Batch events for efficiency
                batch_buffer.append(event_data)

                if len(batch_buffer) >= 5:  # Batch size
                    yield ServerSentEvent(
                        data=json.dumps({"batch": batch_buffer}),
                        event="data_batch",
                        id=f"batch-{i // 5}",
                    )
                    batch_buffer = []
            else:
                # Send individual events
                yield ServerSentEvent(
                    data=json.dumps(event_data), event="data_point", id=str(i)
                )

            await asyncio.sleep(0.1)

        # Send any remaining batched data
        if batch_buffer:
            yield ServerSentEvent(
                data=json.dumps({"batch": batch_buffer}),
                event="data_batch",
                id="final-batch",
            )

    return EventSourceResponse(compressed_stream())


# Test application
app = Starlette(
    routes=[
        Route("/protocols", multi_protocol_endpoint),
        Route("/compressed", compressed_protocol_endpoint),
    ]
)

if __name__ == "__main__":
    """
    DEMONSTRATION STEPS:
    1. Run server: python custom_protocols.py

    2. Test task monitoring protocol:
       curl -N -H "X-Protocol-Version: 1.0" -H "X-Client-Features: batching,compression" \
            "http://localhost:8000/protocols?protocol=task"

    3. Test health monitoring protocol:
       curl -N "http://localhost:8000/protocols?protocol=health"

    4. Test compressed/batched protocol:
       curl -N -H "X-Client-Features: batching" \
            "http://localhost:8000/compressed"

    CUSTOM PROTOCOL BENEFITS:

    1. **Structured Communication**:
       - Predefined message formats
       - Type safety and validation
       - Clear contract between client/server

    2. **Protocol Negotiation**:
       - Version compatibility checking
       - Feature capability exchange
       - Graceful degradation

    3. **Domain-Specific Optimization**:
       - Specialized event types
       - Efficient data encoding
       - Batch operations for performance

    4. **Error Handling**:
       - Protocol-aware error messages
       - Structured error information
       - Recovery mechanisms

    PRODUCTION PATTERNS:
    - Define clear message schemas
    - Implement protocol versioning
    - Handle capability negotiation
    - Optimize for specific use cases
    - Document protocol specifications
    """
    import uvicorn

    print("🚀 Starting custom protocols demonstration server...")
    print("📋 Available endpoints:")
    print("   /protocols?protocol=task   - Task monitoring protocol")
    print("   /protocols?protocol=health - Health monitoring protocol")
    print("   /compressed                - Batching and compression demo")
    print("💡 Use X-Protocol-Version and X-Client-Features headers")

    uvicorn.run(app, host="localhost", port=8000, log_level="info")
