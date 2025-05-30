"""
Minimal Server-Sent Events (SSE) example demonstrating core concepts.

This example shows the essential SSE patterns:
- Simple event streaming with automatic termination
- Endless event streaming with proper cleanup
- HTML client with JavaScript EventSource
- Both finite and infinite stream patterns

For more advanced features, see the examples/ directory.

Usage:
    python example.py

Then visit: http://localhost:8000
"""

import asyncio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from sse_starlette import EventSourceResponse

HTML_CLIENT = """
<!DOCTYPE html>
<html>
<head>
    <title>SSE Example</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .demo { margin: 20px 0; padding: 20px; border: 1px solid #ccc; }
        .output { background: #f5f5f5; padding: 10px; margin: 10px 0; min-height: 50px; }
    </style>
</head>
<body>
    <h1>Server-Sent Events Example</h1>

    <div class="demo">
        <h2>Finite Stream (numbers 1-5)</h2>
        <button onclick="startFiniteStream()">Start Stream</button>
        <div id="finite-output" class="output">Click start to begin...</div>
    </div>

    <div class="demo">
        <h2>Endless Stream</h2>
        <button onclick="startEndlessStream()">Start Stream</button>
        <button onclick="stopEndlessStream()">Stop Stream</button>
        <div id="endless-output" class="output">Click start to begin...</div>
    </div>

    <script>
        let endlessSource = null;

        function startFiniteStream() {
            const output = document.getElementById('finite-output');
            output.innerHTML = 'Connecting...';

            // EventSource automatically handles SSE protocol
            const eventSource = new EventSource('/numbers');

            eventSource.onmessage = function(event) {
                output.innerHTML += 'Received: ' + event.data + '<br>';
            };

            eventSource.onerror = function() {
                output.innerHTML += 'Stream ended.<br>';
                eventSource.close();
            };
        }

        function startEndlessStream() {
            if (endlessSource) return; // Already running

            const output = document.getElementById('endless-output');
            output.innerHTML = 'Connecting...<br>';

            endlessSource = new EventSource('/endless');

            endlessSource.onmessage = function(event) {
                output.innerHTML += 'Count: ' + event.data + '<br>';
                // Keep only last 10 messages
                const lines = output.innerHTML.split('<br>');
                if (lines.length > 10) {
                    output.innerHTML = lines.slice(-10).join('<br>');
                }
            };

            endlessSource.onerror = function() {
                output.innerHTML += 'Connection lost.<br>';
                endlessSource = null;
            };
        }

        function stopEndlessStream() {
            if (endlessSource) {
                endlessSource.close();
                endlessSource = null;
                document.getElementById('endless-output').innerHTML += 'Stream stopped by user.<br>';
            }
        }
    </script>
</body>
</html>
"""


async def finite_number_stream():
    """
    Demonstrates finite SSE stream that automatically terminates.

    This is the simplest SSE pattern - stream a fixed set of data
    and let the connection close naturally when the generator ends.
    """
    for number in range(1, 6):  # Numbers 1 through 5
        # Each yield sends one SSE event to the client
        # The dict format automatically creates: data: {number}
        yield {"data": number}
        await asyncio.sleep(1)  # 1 second between events


async def endless_counter_stream(request: Request):
    """
    Demonstrates endless SSE stream with proper cleanup.

    Key concepts:
    - Infinite loop for continuous streaming
    - Client disconnect detection via request.is_disconnected()
    - Exception handling for graceful cleanup
    - asyncio.CancelledError for proper resource cleanup
    """
    counter = 0

    try:
        while True:
            counter += 1
            yield {"data": counter}
            await asyncio.sleep(0.5)  # 500ms between events

    except asyncio.CancelledError:
        # This exception is raised when:
        # 1. Client closes the browser/tab
        # 2. Client calls eventSource.close()
        # 3. Server is shutting down
        #
        # Always re-raise CancelledError to ensure proper cleanup
        raise


# Starlette route handlers
async def home_page(request: Request) -> HTMLResponse:
    """Serve the HTML demo page."""
    return HTMLResponse(HTML_CLIENT)


async def numbers_endpoint(request: Request) -> EventSourceResponse:
    """SSE endpoint for finite number stream."""
    return EventSourceResponse(finite_number_stream())


async def endless_endpoint(request: Request) -> EventSourceResponse:
    """SSE endpoint for endless counter stream."""
    return EventSourceResponse(endless_counter_stream(request))


# Application setup
app = Starlette(
    routes=[
        Route("/", endpoint=home_page),
        Route("/numbers", endpoint=numbers_endpoint),
        Route("/endless", endpoint=endless_endpoint),
    ]
)

if __name__ == "__main__":
    print("Starting SSE example server...")
    print("Visit: http://localhost:8000")
    print("\nEndpoints:")
    print("  / - Demo page with JavaScript client")
    print("  /numbers - Finite stream (1-5)")
    print("  /endless - Infinite counter stream")

    uvicorn.run(app, host="0.0.0.0", port=8000)
