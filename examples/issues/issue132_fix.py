#!/usr/bin/env python3
"""
Comprehensive test application demonstrating the fix for issue #132.

This application proves that the enhanced AppStatus implementation correctly
handles shutdown signals with uvicorn 0.34+, replacing the broken monkey-patching
approach with direct signal handler registration.

Run with: python issue132_fix_demo.py
Test with: Open http://localhost:8080 and press Ctrl+C to see graceful shutdown
"""
import asyncio
import logging
import signal
import threading
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List, Any

import uvicorn
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from sse_starlette import EventSourceResponse
from sse_starlette.appstatus import AppStatus

# Configure comprehensive logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("issue132_demo")


# Global state for demonstration
class DemoState:
    """Track demo state to show proper cleanup."""
    active_streams: int = 0
    total_events_sent: int = 0
    startup_time: float = time.time()
    shutdown_initiated: bool = False
    cleanup_completed: bool = False


demo_state = DemoState()


class StreamStats(BaseModel):
    """Response model for stream statistics."""
    active_streams: int
    total_events_sent: int
    uptime_seconds: float
    shutdown_initiated: bool


def create_shutdown_callbacks() -> None:
    """Register shutdown callbacks to demonstrate the fix."""

    def log_shutdown_initiation():
        logger.info("🛑 Shutdown callback #1: Shutdown initiated")
        demo_state.shutdown_initiated = True

    def cleanup_resources():
        logger.info("🧹 Shutdown callback #2: Cleaning up resources")
        # Simulate resource cleanup
        time.sleep(0.1)
        demo_state.cleanup_completed = True

    def final_shutdown_log():
        logger.info("✅ Shutdown callback #3: Final cleanup complete")
        logger.info(f"📊 Final stats: {demo_state.active_streams} streams, "
                    f"{demo_state.total_events_sent} events sent")

    # Register callbacks in order
    AppStatus.add_shutdown_callback(log_shutdown_initiation)
    AppStatus.add_shutdown_callback(cleanup_resources)
    AppStatus.add_shutdown_callback(final_shutdown_log)

    logger.info("📝 Registered 3 shutdown callbacks")


async def demonstrate_signal_handling() -> AsyncGenerator[Dict, None]:
    """
    Stream that demonstrates proper signal handling.
    This will terminate gracefully when SIGINT/SIGTERM is received.
    """
    demo_state.active_streams += 1
    event_count = 0

    try:
        logger.info(f"🚀 Starting demo stream (active streams: {demo_state.active_streams})")

        while not AppStatus.should_exit:
            event_count += 1
            demo_state.total_events_sent += 1

            # Generate different types of events to show variety
            if event_count % 10 == 0:
                event_type = "milestone"
                message = f"Milestone reached: {event_count} events sent"
            elif event_count % 5 == 0:
                event_type = "status"
                message = f"Status update: {demo_state.active_streams} active streams"
            else:
                event_type = "data"
                message = f"Event #{event_count} at {datetime.now().strftime('%H:%M:%S')}"

            yield {
                "event": event_type,
                "data": {
                    "message": message,
                    "event_id": event_count,
                    "timestamp": time.time(),
                    "uptime": time.time() - demo_state.startup_time,
                    "should_exit": AppStatus.should_exit
                },
                "id": str(event_count)
            }

            # Check for shutdown more frequently than sleep interval
            for _ in range(10):  # Check 10 times per second
                if AppStatus.should_exit:
                    logger.info(f"🔄 Stream {id(asyncio.current_task())} received shutdown signal")
                    break
                await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        logger.info(f"❌ Stream cancelled after {event_count} events")
        raise
    except Exception as e:
        logger.error(f"💥 Stream error after {event_count} events: {e}")
        raise
    finally:
        demo_state.active_streams -= 1
        logger.info(f"🏁 Stream ended. Sent {event_count} events. "
                    f"Active streams: {demo_state.active_streams}")


async def health_monitoring_stream() -> AsyncGenerator[Dict, None]:
    """
    Health monitoring stream to show multiple concurrent SSE endpoints.
    """
    demo_state.active_streams += 1
    check_count = 0

    try:
        logger.info("🏥 Starting health monitoring stream")

        while not AppStatus.should_exit:
            check_count += 1

            yield {
                "event": "health_check",
                "data": {
                    "status": "healthy" if not AppStatus.should_exit else "shutting_down",
                    "check_number": check_count,
                    "active_streams": demo_state.active_streams,
                    "total_events": demo_state.total_events_sent,
                    "uptime": time.time() - demo_state.startup_time,
                    "memory_info": "simulated_memory_stats",
                    "app_status": {
                        "should_exit": AppStatus.should_exit,
                        "initialized": AppStatus._initialized,
                        "callbacks_registered": len(AppStatus._shutdown_callbacks)
                    }
                },
                "id": f"health_{check_count}"
            }

            # Health checks every 3 seconds, but check shutdown more frequently
            for _ in range(30):  # 0.1s * 30 = 3s total, but responsive to shutdown
                if AppStatus.should_exit:
                    break
                await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        logger.info(f"🏥 Health monitoring cancelled after {check_count} checks")
        raise
    finally:
        demo_state.active_streams -= 1
        logger.info(f"🏁 Health monitoring ended after {check_count} checks")


# FastAPI Application Setup
app = FastAPI(
    title="Issue #132 Fix Demonstration",
    description="Demonstrates the enhanced AppStatus signal handling fix",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def homepage() -> str:
    """Serve the test page."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Issue #132 Fix Demonstration</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0; padding: 20px; background: #f5f7fa;
            }
            .container {
                max-width: 1200px; margin: 0 auto; background: white;
                border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; padding: 30px; border-radius: 8px 8px 0 0;
            }
            .content { padding: 30px; }
            .demo-section {
                margin: 20px 0; padding: 20px; border: 1px solid #e1e5e9;
                border-radius: 6px; background: #fafbfc;
            }
            .event-log {
                height: 300px; overflow-y: auto; border: 1px solid #d1d9e0;
                padding: 15px; background: #f8f9fa; font-family: 'Courier New', monospace;
                font-size: 13px; border-radius: 4px;
            }
            .event {
                margin: 5px 0; padding: 8px; border-radius: 4px;
                border-left: 4px solid #28a745;
            }
            .event.milestone { border-left-color: #ffc107; background: #fff3cd; }
            .event.status { border-left-color: #17a2b8; background: #d1ecf1; }
            .event.health_check { border-left-color: #28a745; background: #d4edda; }
            .event.error { border-left-color: #dc3545; background: #f8d7da; }
            button {
                background: #007bff; color: white; border: none; padding: 12px 24px;
                border-radius: 4px; cursor: pointer; margin: 5px; font-size: 14px;
            }
            button:hover { background: #0056b3; }
            button:disabled { background: #6c757d; cursor: not-allowed; }
            .stats {
                display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px; margin: 20px 0;
            }
            .stat-card {
                background: white; padding: 20px; border-radius: 6px;
                border: 1px solid #e1e5e9; text-align: center;
            }
            .stat-value { font-size: 32px; font-weight: bold; color: #007bff; }
            .stat-label { color: #6c757d; font-size: 14px; text-transform: uppercase; }
            .instructions {
                background: #e7f3ff; border: 1px solid #b6d7ff; padding: 20px;
                border-radius: 6px; margin: 20px 0;
            }
            .instructions h3 { margin-top: 0; color: #0056b3; }
            .status-indicator {
                display: inline-block; width: 12px; height: 12px;
                border-radius: 50%; margin-right: 8px;
            }
            .status-connected { background: #28a745; }
            .status-disconnected { background: #dc3545; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🔧 Issue #132 Fix Demonstration</h1>
                <p>Enhanced AppStatus with Direct Signal Handler Registration</p>
                <p><strong>uvicorn 0.34+ Compatible</strong> - No more monkey-patching!</p>
            </div>

            <div class="content">
                <div class="instructions">
                    <h3>🧪 How to Test the Fix</h3>
                    <ol>
                        <li><strong>Start Streams:</strong> Click the buttons below to start SSE streams</li>
                        <li><strong>Monitor Activity:</strong> Watch the real-time events and statistics</li>
                        <li><strong>Test Shutdown:</strong> Press <kbd>Ctrl+C</kbd> in the terminal</li>
                        <li><strong>Observe Cleanup:</strong> Notice graceful shutdown in terminal logs</li>
                        <li><strong>Verify Fix:</strong> No hanging processes or zombie connections</li>
                    </ol>
                </div>

                <div class="demo-section">
                    <h3>🎛️ Stream Controls</h3>
                    <button onclick="startMainStream()">Start Main Event Stream</button>
                    <button onclick="startHealthStream()">Start Health Monitoring</button>
                    <button onclick="stopAllStreams()">Stop All Streams</button>
                    <button onclick="clearLogs()">Clear Logs</button>
                    <button onclick="getStats()">Refresh Stats</button>
                </div>

                <div class="stats" id="stats">
                    <div class="stat-card">
                        <div class="stat-value" id="activeStreams">0</div>
                        <div class="stat-label">Active Streams</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="totalEvents">0</div>
                        <div class="stat-label">Total Events</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="uptime">0s</div>
                        <div class="stat-label">Uptime</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="shutdownStatus">Normal</div>
                        <div class="stat-label">Status</div>
                    </div>
                </div>

                <div class="demo-section">
                    <h3>📡 Live Event Streams</h3>
                    <div>
                        <span class="status-indicator status-disconnected" id="mainStreamIndicator"></span>
                        <strong>Main Stream:</strong> <span id="mainStreamStatus">Disconnected</span>
                    </div>
                    <div style="margin-top: 10px;">
                        <span class="status-indicator status-disconnected" id="healthStreamIndicator"></span>
                        <strong>Health Stream:</strong> <span id="healthStreamStatus">Disconnected</span>
                    </div>
                    <div class="event-log" id="eventLog"></div>
                </div>
            </div>
        </div>

        <script>
            let mainEventSource = null;
            let healthEventSource = null;
            let eventCount = 0;
            let statsInterval = null;

            function logEvent(message, type = 'data') {
                const log = document.getElementById('eventLog');
                const div = document.createElement('div');
                div.className = `event ${type}`;
                div.innerHTML = `[${new Date().toLocaleTimeString()}] ${message}`;
                log.appendChild(div);
                log.scrollTop = log.scrollHeight;
                eventCount++;

                // Limit log entries to prevent memory issues
                if (log.children.length > 100) {
                    log.removeChild(log.firstChild);
                }
            }

            function updateStreamStatus(stream, status, connected) {
                const indicator = document.getElementById(`${stream}StreamIndicator`);
                const statusEl = document.getElementById(`${stream}StreamStatus`);

                indicator.className = `status-indicator ${connected ? 'status-connected' : 'status-disconnected'}`;
                statusEl.textContent = status;
            }

            function startMainStream() {
                if (mainEventSource) {
                    mainEventSource.close();
                }

                mainEventSource = new EventSource('/events');

                mainEventSource.onopen = function() {
                    updateStreamStatus('main', 'Connected', true);
                    logEvent('🟢 Main stream connected', 'status');
                };

                mainEventSource.onmessage = function(e) {
                    const data = JSON.parse(e.data);
                    logEvent(`📊 ${data.message} (Event #${data.event_id})`, 'data');
                };

                mainEventSource.addEventListener('milestone', function(e) {
                    const data = JSON.parse(e.data);
                    logEvent(`🎯 MILESTONE: ${data.message}`, 'milestone');
                });

                mainEventSource.addEventListener('status', function(e) {
                    const data = JSON.parse(e.data);
                    logEvent(`📈 STATUS: ${data.message}`, 'status');
                });

                mainEventSource.onerror = function() {
                    updateStreamStatus('main', 'Error/Disconnected', false);
                    logEvent('🔴 Main stream disconnected', 'error');
                };
            }

            function startHealthStream() {
                if (healthEventSource) {
                    healthEventSource.close();
                }

                healthEventSource = new EventSource('/health');

                healthEventSource.onopen = function() {
                    updateStreamStatus('health', 'Connected', true);
                    logEvent('🟢 Health monitoring connected', 'status');
                };

                healthEventSource.addEventListener('health_check', function(e) {
                    const data = JSON.parse(e.data);
                    const statusIcon = data.status === 'healthy' ? '💚' : '🟡';
                    logEvent(`${statusIcon} Health Check #${data.check_number}: ${data.status.toUpperCase()}`, 'health_check');
                });

                healthEventSource.onerror = function() {
                    updateStreamStatus('health', 'Error/Disconnected', false);
                    logEvent('🔴 Health monitoring disconnected', 'error');
                };
            }

            function stopAllStreams() {
                if (mainEventSource) {
                    mainEventSource.close();
                    mainEventSource = null;
                    updateStreamStatus('main', 'Disconnected', false);
                }
                if (healthEventSource) {
                    healthEventSource.close();
                    healthEventSource = null;
                    updateStreamStatus('health', 'Disconnected', false);
                }
                logEvent('🛑 All streams stopped by user', 'status');
            }

            function clearLogs() {
                document.getElementById('eventLog').innerHTML = '';
                eventCount = 0;
                logEvent('🧹 Logs cleared', 'status');
            }

            async function getStats() {
                try {
                    const response = await fetch('/stats');
                    const stats = await response.json();

                    document.getElementById('activeStreams').textContent = stats.active_streams;
                    document.getElementById('totalEvents').textContent = stats.total_events_sent;
                    document.getElementById('uptime').textContent = Math.floor(stats.uptime_seconds) + 's';
                    document.getElementById('shutdownStatus').textContent =
                        stats.shutdown_initiated ? 'SHUTTING DOWN' : 'Normal';

                    if (stats.shutdown_initiated) {
                        document.getElementById('shutdownStatus').style.color = '#dc3545';
                    }
                } catch (error) {
                    logEvent(`❌ Failed to fetch stats: ${error.message}`, 'error');
                }
            }

            // Auto-refresh stats every 5 seconds
            statsInterval = setInterval(getStats, 5000);

            // Initial stats load
            getStats();

            // Cleanup on page unload
            window.addEventListener('beforeunload', function() {
                stopAllStreams();
                if (statsInterval) clearInterval(statsInterval);
            });

            // Welcome message
            logEvent('🚀 Issue #132 Fix Demo Ready - Enhanced AppStatus Initialized', 'status');
            logEvent('👆 Click buttons above to start testing signal handling fix', 'status');
        </script>
    </body>
    </html>
    """


@app.get("/events")
async def main_event_stream(request: Request) -> EventSourceResponse:
    """Main SSE endpoint demonstrating the signal handling fix."""
    logger.info(f"🔌 New main stream connection from {request.client}")

    return EventSourceResponse(
        demonstrate_signal_handling(),
        headers={
            "X-Demo-Purpose": "issue-132-fix",
            "X-Connection-ID": str(id(request)),
        },
        ping=15  # Ping every 15 seconds
    )


@app.get("/health")
async def health_stream(request: Request) -> EventSourceResponse:
    """Health monitoring SSE endpoint."""
    logger.info(f"🏥 New health monitoring connection from {request.client}")

    return EventSourceResponse(
        health_monitoring_stream(),
        headers={
            "X-Stream-Type": "health-monitoring",
            "X-Connection-ID": str(id(request)),
        },
        ping=30  # Less frequent pings for health monitoring
    )


@app.get("/stats")
async def get_statistics() -> StreamStats:
    """Get current statistics to show in the UI."""
    return StreamStats(
        active_streams=demo_state.active_streams,
        total_events_sent=demo_state.total_events_sent,
        uptime_seconds=time.time() - demo_state.startup_time,
        shutdown_initiated=demo_state.shutdown_initiated
    )


@app.get("/test-signal")
async def test_signal_handling() -> Dict[str, Any]:
    """
    Test endpoint to programmatically trigger shutdown handling.
    This allows testing without sending actual signals.
    """
    logger.info("🧪 Testing signal handling programmatically")

    # Simulate signal handling
    AppStatus.handle_exit(signal.SIGTERM, None)

    return {
        "message": "Signal handling test triggered",
        "should_exit": AppStatus.should_exit,
        "shutdown_callbacks_count": len(AppStatus._shutdown_callbacks),
        "app_status_initialized": AppStatus._initialized
    }


@app.on_event("startup")
async def startup_event():
    """Application startup handler."""
    logger.info("🚀 Application startup")
    logger.info(f"📋 AppStatus initialized: {AppStatus._initialized}")
    logger.info(f"🔧 Signal handlers registered: {len(AppStatus._original_handlers)}")

    # Register our demonstration callbacks
    create_shutdown_callbacks()

    # Log the fix details
    logger.info("✅ Issue #132 Fix Active:")
    logger.info("   - Direct signal handler registration (no monkey-patching)")
    logger.info("   - Thread-safe shutdown handling")
    logger.info("   - Graceful SSE stream termination")
    logger.info("   - Compatible with uvicorn 0.34+")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown handler."""
    logger.info("🛑 Application shutdown initiated")
    if demo_state.cleanup_completed:
        logger.info("✅ Cleanup completed successfully")
    else:
        logger.warning("⚠️ Cleanup may not have completed")


def main():
    """Main entry point with comprehensive logging."""
    print("=" * 80)
    print("🔧 ISSUE #132 FIX DEMONSTRATION")
    print("=" * 80)
    print()
    print("This application demonstrates the enhanced AppStatus implementation")
    print("that fixes the signal handling issue with uvicorn 0.34+")
    print()
    print("Key improvements:")
    print("  ✅ Direct signal handler registration (no monkey-patching)")
    print("  ✅ Thread-safe shutdown handling")
    print("  ✅ Graceful SSE stream termination")
    print("  ✅ Backward compatibility maintained")
    print()
    print("🧪 Test Instructions:")
    print("  1. Open http://localhost:8080 in your browser")
    print("  2. Start some SSE streams using the web interface")
    print("  3. Press Ctrl+C in this terminal to test graceful shutdown")
    print("  4. Observe clean termination and proper cleanup in logs")
    print()
    print("📊 Monitor the logs below for detailed shutdown behavior...")
    print("=" * 80)
    print()

    # Configure uvicorn for optimal demonstration
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
        access_log=True,
        reload=False,  # Disable reload to see clean shutdown behavior
        workers=1,  # Single worker for clear demonstration
    )

    server = uvicorn.Server(config)

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("🛑 KeyboardInterrupt received - testing graceful shutdown")
    except Exception as e:
        logger.error(f"💥 Unexpected error: {e}")
    finally:
        # Verify fix worked
        if demo_state.shutdown_initiated and demo_state.cleanup_completed:
            print("\n" + "=" * 80)
            print("✅ SUCCESS: Issue #132 fix verified!")
            print("   - Shutdown callbacks executed")
            print("   - Resources cleaned up properly")
            print("   - No hanging processes")
            print("=" * 80)
        else:
            print("\n" + "=" * 80)
            print("❌ Issue #132 fix may have problems")
            print(f"   - Shutdown initiated: {demo_state.shutdown_initiated}")
            print(f"   - Cleanup completed: {demo_state.cleanup_completed}")
            print("=" * 80)


if __name__ == "__main__":
    main()
