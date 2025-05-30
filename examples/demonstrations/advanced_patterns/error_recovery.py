# demonstrations/advanced_patterns/error_recovery.py
"""
DEMONSTRATION: Error Recovery in SSE Streams

PURPOSE:
Shows sophisticated error handling and recovery patterns for production SSE.

KEY LEARNING:
- Different types of errors require different recovery strategies
- Stream state can be preserved across errors
- Client-side recovery patterns are essential

PATTERN:
Multi-layered error handling with graceful degradation.
"""

import asyncio
import random
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from sse_starlette import EventSourceResponse


class ErrorType(Enum):
    """Different types of errors that can occur in SSE streams."""
    TRANSIENT = "transient"  # Temporary issues, can retry
    RECOVERABLE = "recoverable"  # Errors we can work around
    FATAL = "fatal"  # Unrecoverable errors


@dataclass
class StreamState:
    """Maintains state across error recovery attempts."""
    last_successful_event: int = 0
    error_count: int = 0
    recovery_attempts: int = 0
    start_time: float = 0

    def should_abort(self, max_errors: int = 5) -> bool:
        """Determine if stream should be aborted due to too many errors."""
        return self.error_count >= max_errors


class ErrorSimulator:
    """Simulates various error conditions for demonstration."""

    def __init__(self):
        self.error_probability = 0.1  # 10% chance of error
        self.error_types = list(ErrorType)

    def should_error_occur(self) -> bool:
        """Randomly determine if an error should occur."""
        return random.random() < self.error_probability

    def get_random_error(self) -> tuple[ErrorType, Exception]:
        """Generate a random error for demonstration."""
        error_type = random.choice(self.error_types)

        if error_type == ErrorType.TRANSIENT:
            return error_type, ConnectionError("Temporary database connection lost")
        elif error_type == ErrorType.RECOVERABLE:
            return error_type, ValueError("Invalid data format, using fallback")
        else:  # FATAL
            return error_type, RuntimeError("Critical system failure")


async def resilient_stream_with_recovery(request: Request, stream_state: StreamState):
    """
    Stream that implements comprehensive error recovery.
    """
    error_simulator = ErrorSimulator()

    try:
        # Resume from last successful event
        start_event = stream_state.last_successful_event + 1

        for i in range(start_event, start_event + 20):
            # Check for client disconnect
            if await request.is_disconnected():
                yield {"data": "Client disconnected during recovery", "event": "info"}
                break

            try:
                # Simulate error conditions
                if error_simulator.should_error_occur():
                    error_type, error = error_simulator.get_random_error()
                    raise error

                # Normal event processing
                event_data = {
                    "data": f"Event {i} - State: errors={stream_state.error_count}, recoveries={stream_state.recovery_attempts}",
                    "id": str(i),
                    "event": "data"
                }

                yield event_data
                stream_state.last_successful_event = i

                await asyncio.sleep(0.5)

            except ConnectionError as e:
                # TRANSIENT error - can retry
                stream_state.error_count += 1
                print(f"🔄 Transient error at event {i}: {e}")

                yield {
                    "data": f"Temporary connection issue, retrying... (attempt {stream_state.recovery_attempts + 1})",
                    "event": "recovery"
                }

                # Wait and retry
                await asyncio.sleep(1)
                stream_state.recovery_attempts += 1
                continue  # Retry this event

            except ValueError as e:
                # RECOVERABLE error - use fallback
                stream_state.error_count += 1
                print(f"⚠️ Recoverable error at event {i}: {e}")

                # Send fallback data
                fallback_data = {
                    "data": f"Fallback data for event {i} (original data corrupted)",
                    "id": str(i),
                    "event": "fallback"
                }

                yield fallback_data
                stream_state.last_successful_event = i
                continue  # Continue with next event

            except RuntimeError as e:
                # FATAL error - cannot recover
                print(f"💀 Fatal error at event {i}: {e}")

                yield {
                    "data": f"Fatal error occurred: {e}",
                    "event": "fatal_error"
                }

                # Abort stream
                return

    except Exception as e:
        # Unexpected error
        print(f"💥 Unexpected error in stream: {e}")
        yield {
            "data": f"Unexpected stream error: {e}",
            "event": "stream_error"
        }

    finally:
        # Always send completion info
        yield {
            "data": f"Stream completed - Events: {stream_state.last_successful_event}, Errors: {stream_state.error_count}",
            "event": "completion"
        }


async def error_recovery_endpoint(request: Request):
    """
    SSE endpoint with comprehensive error recovery.
    """
    import time

    # Create stream state for this connection
    stream_state = StreamState(start_time=time.time())

    # Check if client is requesting resumption
    last_event_id = request.headers.get("Last-Event-ID")
    if last_event_id:
        try:
            stream_state.last_successful_event = int(last_event_id)
            print(f"📍 Resuming stream from event {last_event_id}")
        except ValueError:
            print(f"⚠️ Invalid Last-Event-ID: {last_event_id}")

    return EventSourceResponse(
        resilient_stream_with_recovery(request, stream_state),
        ping=3,
        send_timeout=10.0
    )


async def circuit_breaker_endpoint(request: Request):
    """
    Demonstrates circuit breaker pattern for SSE.
    """

    class CircuitBreaker:
        def __init__(self, failure_threshold=3, recovery_timeout=5):
            self.failure_threshold = failure_threshold
            self.recovery_timeout = recovery_timeout
            self.failure_count = 0
            self.last_failure_time = 0
            self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

        def is_available(self) -> bool:
            """Check if service is available according to circuit breaker."""
            import time
            current_time = time.time()

            if self.state == "OPEN":
                if current_time - self.last_failure_time > self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    return True
                return False

            return True

        def record_success(self):
            """Record successful operation."""
            self.failure_count = 0
            self.state = "CLOSED"

        def record_failure(self):
            """Record failed operation."""
            import time
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"

    circuit_breaker = CircuitBreaker()

    async def circuit_breaker_stream():
        for i in range(1, 30):
            try:
                # Check circuit breaker
                if not circuit_breaker.is_available():
                    yield {
                        "data": f"Service unavailable (circuit breaker OPEN) - event {i}",
                        "event": "circuit_open"
                    }
                    await asyncio.sleep(1)
                    continue

                # Simulate service calls with random failures
                if random.random() < 0.3:  # 30% failure rate
                    circuit_breaker.record_failure()
                    raise ConnectionError("Service call failed")

                # Success
                circuit_breaker.record_success()
                yield {
                    "data": f"Service call {i} successful (circuit breaker: {circuit_breaker.state})",
                    "id": str(i),
                    "event": "success"
                }

            except Exception as e:
                yield {
                    "data": f"Service error: {e} (failures: {circuit_breaker.failure_count})",
                    "event": "service_error"
                }

            await asyncio.sleep(0.8)

    return EventSourceResponse(circuit_breaker_stream(), ping=5)


# Test application
app = Starlette(routes=[
    Route("/error-recovery", error_recovery_endpoint),
    Route("/circuit-breaker", circuit_breaker_endpoint)
])

if __name__ == "__main__":
    """
    DEMONSTRATION STEPS:
    1. Run server: python error_recovery.py
    2. Test error recovery: curl -N http://localhost:8000/error-recovery
    3. Test with resumption: curl -N -H "Last-Event-ID: 5" http://localhost:8000/error-recovery
    4. Test circuit breaker: curl -N http://localhost:8000/circuit-breaker

    ERROR RECOVERY PATTERNS:

    1. **Transient Errors**: Temporary issues that resolve themselves
       - Strategy: Retry with backoff
       - Examples: Network timeouts, temporary service unavailability

    2. **Recoverable Errors**: Issues with workarounds available
       - Strategy: Use fallback data or alternative methods
       - Examples: Data format issues, missing optional data

    3. **Fatal Errors**: Unrecoverable issues requiring stream termination
       - Strategy: Graceful shutdown with error notification
       - Examples: Authentication failures, critical system errors

    4. **Circuit Breaker**: Prevent cascading failures
       - Strategy: Temporarily stop calling failing services
       - Benefits: System stability, faster failure detection

    PRODUCTION CONSIDERATIONS:
    - Implement client-side retry logic with exponential backoff
    - Use Last-Event-ID header for stream resumption
    - Monitor error rates and patterns
    - Set appropriate timeout values
    - Provide meaningful error messages to clients
    """
    import uvicorn

    print("🚀 Starting error recovery demonstration server...")
    print("📋 Available endpoints:")
    print("   /error-recovery   - Comprehensive error recovery patterns")
    print("   /circuit-breaker  - Circuit breaker pattern demo")
    print("💡 Use Last-Event-ID header to test stream resumption")

    uvicorn.run(app, host="localhost", port=8000, log_level="info")
