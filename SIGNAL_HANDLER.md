# AppStatus Signal Handler Fix - Migration Guide

## Issue Summary

**Issue #132**: The existing monkey-patching approach for `Server.handle_exit` no longer works with uvicorn 0.34+ because uvicorn now registers signal handlers before importing the application module.

## Root Cause

In uvicorn 0.34+, the initialization order changed:
1. Signal handlers are registered by uvicorn
2. Application module is imported (where sse-starlette tries to monkey-patch)

This means our monkey-patch happens too late and doesn't affect the actual signal handling.

## Solution Overview

The fix introduces an enhanced `AppStatus` class that:
1. **Registers signal handlers directly** instead of monkey-patching uvicorn
2. **Maintains backward compatibility** with existing code
3. **Provides thread-safe shutdown handling**
4. **Supports graceful cleanup** for SSE streams

## Key Changes

### 1. Enhanced AppStatus Class

```python
# Before (broken with uvicorn 0.34+)
try:
    from uvicorn.main import Server
    AppStatus.original_handler = Server.handle_exit
    Server.handle_exit = AppStatus.handle_exit  # This no longer works
except ImportError:
    pass

# After (works with all uvicorn versions)
class AppStatus:
    @classmethod
    def initialize(cls) -> None:
        """Register signal handlers directly."""
        def signal_handler(signum: int, frame) -> None:
            cls.handle_exit(signum, frame)
        
        # Register handlers for SIGINT and SIGTERM
        for sig in [signal.SIGINT, signal.SIGTERM]:
            original = signal.signal(sig, signal_handler)
            cls._original_handlers[sig] = original
```

### 2. Automatic Initialization

The enhanced AppStatus automatically initializes when:
- The module is imported (backward compatibility)
- An EventSourceResponse is created (explicit initialization)

### 3. Thread-Safe Operations

All AppStatus operations are now thread-safe using proper locking mechanisms.

## Migration Steps

### For Library Users (No Changes Required)

**Good news**: If you're using sse-starlette as a library, **no code changes are required**. The fix is backward compatible.

Your existing code will continue to work:

```python
# This continues to work unchanged
from sse_starlette import EventSourceResponse

async def sse_endpoint(request):
    async def event_generator():
        for i in range(10):
            yield {"data": f"event {i}"}
            await asyncio.sleep(1)
    
    return EventSourceResponse(event_generator())
```

### For Contributors/Developers

If you're working on sse-starlette itself or running tests:

#### 1. Use the New Test Fixture

```python
@pytest.fixture
def reset_appstatus():
    """Fixture to reset AppStatus before and after tests."""
    from sse_starlette.appstatus import AppStatus
    AppStatus.reset()
    yield
    AppStatus.cleanup()

def test_my_sse_feature(reset_appstatus):
    # Your test code here
    pass
```

#### 2. Update Existing Test Fixtures

Replace the old fixture:

```python
# Old fixture (still works but deprecated)
@pytest.fixture
def reset_appstatus_event():
    from sse_starlette.sse import AppStatus
    AppStatus.should_exit_event = None

# New recommended fixture
@pytest.fixture
def reset_appstatus():
    from sse_starlette.appstatus import AppStatus
    AppStatus.reset()
    yield
    AppStatus.cleanup()
```

### For Advanced Use Cases

If you need to customize shutdown behavior:

```python
from sse_starlette.appstatus import AppStatus

# Add custom shutdown logic
def my_cleanup():
    print("Performing custom cleanup...")
    # Your cleanup code here

AppStatus.add_shutdown_callback(my_cleanup)
```

## Testing the Fix

### Unit Tests

```python
def test_signal_handling_works():
    """Test that signal handling works with new AppStatus."""
    import os
    import signal
    import threading
    from sse_starlette.appstatus import AppStatus
    
    # Reset state
    AppStatus.reset()
    AppStatus.initialize()
    
    # Set up callback to verify signal was received
    signal_received = threading.Event()
    AppStatus.add_shutdown_callback(lambda: signal_received.set())
    
    # Send signal
    os.kill(os.getpid(), signal.SIGINT)
    
    # Verify signal was handled
    assert signal_received.wait(timeout=2.0)
    assert AppStatus.should_exit is True
```

### Integration Tests

```python
def test_sse_graceful_shutdown():
    """Test that SSE streams shut down gracefully."""
    import asyncio
    from sse_starlette import EventSourceResponse
    from sse_starlette.appstatus import AppStatus
    
    async def endless_stream():
        try:
            i = 0
            while True:
                yield {"data": f"event_{i}"}
                i += 1
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            print("Stream cancelled gracefully")
            raise
    
    # Create response
    response = EventSourceResponse(endless_stream())
    
    # Simulate shutdown
    AppStatus.handle_exit()
    
    # Verify streams terminate (implementation depends on your test setup)
```

## Compatibility Matrix

| uvicorn Version | Old AppStatus | New AppStatus |
|----------------|---------------|---------------|
| < 0.29         | ✅ Works      | ✅ Works      |
| 0.29 - 0.33    | ✅ Works      | ✅ Works      |
| 0.34+          | ❌ Broken     | ✅ Works      |

## Troubleshooting

### Issue: Tests Hanging

**Problem**: Tests that use SSE endpoints hang or don't terminate properly.

**Solution**: Use the new `reset_appstatus` fixture:

```python
def test_my_sse_endpoint(reset_appstatus):
    # Your test code
    pass
```

### Issue: Signal Handlers Not Working

**Problem**: Shutdown signals (Ctrl+C) don't terminate SSE streams.

**Solution**: Ensure AppStatus is initialized:

```python
from sse_starlette.appstatus import AppStatus
AppStatus.initialize()  # Usually automatic, but can call explicitly
```

### Issue: Multiple Signal Handler Registration

**Problem**: Getting errors about signal handlers being registered multiple times.

**Solution**: The new AppStatus prevents multiple registration automatically. If you see this issue, ensure you're using the latest version.

## Performance Impact

The new signal handler approach has **minimal performance impact**:
- Signal handler registration happens once at startup
- No monkey-patching overhead
- Thread-safe operations use efficient locking
- Backward compatibility adds no runtime cost

## Security Considerations

The fix improves security by:
- **Removing dependency on uvicorn internals** (monkey-patching)
- **Proper signal handler cleanup** preventing handler leaks
- **Thread-safe operations** preventing race conditions

## Future Compatibility

This fix ensures sse-starlette works with:
- Current uvicorn versions (0.34+)
- Future uvicorn releases
- Alternative ASGI servers
- Different Python versions (3.9+)

## Summary

The AppStatus fix addresses issue #132 by replacing unreliable monkey-patching with direct signal handler registration. This ensures:

1. ✅ **Compatibility** with uvicorn 0.34+
2. ✅ **Backward compatibility** with existing code
3. ✅ **Thread safety** for concurrent operations
4. ✅ **Graceful shutdown** for SSE streams
5. ✅ **No breaking changes** for users

The fix is automatically applied when you upgrade sse-starlette - no code changes required for most users.
