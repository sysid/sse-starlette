# Shutdown & Cancellation Flow

## Task Group Architecture

When `EventSourceResponse.__call__` is invoked, it creates an `anyio` task group with
four concurrent tasks, each wrapped in `cancel_on_finish`. **Whichever task returns first
cancels all siblings** via `task_group.cancel_scope.cancel()`.

```
EventSourceResponse.__call__(scope, receive, send)
   |
   v
anyio.create_task_group()
   |
   +-- cancel_on_finish(_stream_response)      # pushes SSE data to client
   +-- cancel_on_finish(_ping)                 # keepalive pings every ~15s
   +-- cancel_on_finish(_listen_for_exit_signal_with_grace)  # server shutdown
   +-- cancel_on_finish(_listen_for_disconnect) # client disconnect
   |   (+ optional: data_sender_callable)
   |
   v
All tasks cancelled --> background task (if any) --> return
```

---

## The `cancel_on_finish` Pattern

```python
async def cancel_on_finish(coro):
    await coro()                        # run until coro returns
    task_group.cancel_scope.cancel()    # then cancel ALL sibling tasks
```

This makes the task group a **race**: the first task to complete wins and kills the rest.

---

## Flow 1: Normal Generator Exhaustion

```
Generator yields all items and finishes naturally.

_stream_response         _ping        _exit_signal    _disconnect
      |                    |               |               |
  async for data:          |               |               |
    send(chunk)       sleep(15)       wait(event)     receive()
    send(chunk)            |               |               |
      ...                  |               |               |
  [generator ends]         |               |               |
  self.active = False      |               |               |
  send(more_body=False)    |               |               |
  return                   |               |               |
      |                    |               |               |
  cancel_on_finish ----> CANCEL          CANCEL          CANCEL
      |
      v
  Task group exits cleanly
```

---

## Flow 2: Client Disconnect

```
Client closes connection (browser navigates away, network drop).

_stream_response         _ping        _exit_signal    _disconnect
      |                    |               |               |
  async for data:     sleep(15)       wait(event)     receive()
    send(chunk)            |               |               |
      |                    |               |          http.disconnect
      |                    |               |          self.active=False
      |                    |               |          return
      |                    |               |               |
      |               cancel_on_finish <-------- CANCEL <--+
      |                    |               |
   CANCEL <----------------+----- CANCEL <-+
      |
      v
  Task group exits (generator receives CancelledError)
```

---

## Flow 3: Server Shutdown (No Cooperative Shutdown)

Default behavior when `shutdown_event` is not provided.

```
                          SIGTERM / SIGINT
                               |
                               v
                    Server.handle_exit() [monkey-patched]
                               |
                    AppStatus.should_exit = True
                               |
                               v
              _shutdown_watcher (polls every 0.5s)
                               |
                    detects should_exit == True
                               |
                    broadcasts to all registered anyio.Events
                               |
                               v

_stream_response         _ping        _exit_signal_with_grace    _disconnect
      |                    |                    |                      |
  async for data:     sleep(15)       _listen_for_exit_signal()   receive()
    send(chunk)            |                    |                      |
      |                    |             event.wait() returns          |
      |                    |                    |                      |
      |                    |             shutdown_event = None         |
      |                    |             grace_period = 0              |
      |                    |             --> return immediately        |
      |                    |                    |                      |
   CANCEL <------------ CANCEL <-- cancel_on_finish           CANCEL <-+
      |
      v
  Generator receives CancelledError (no chance for farewell)
  Task group exits
```

---

## Flow 4: Server Shutdown WITH Cooperative Shutdown (Issue #167)

When `shutdown_event` and `shutdown_grace_period` are provided.

```
                          SIGTERM / SIGINT
                               |
                               v
                    AppStatus.should_exit = True
                               |
                    _shutdown_watcher broadcasts
                               |
                               v

_stream_response         _ping        _exit_signal_with_grace    _disconnect
      |                    |                    |                      |
  async for data:     sleep(15)       _listen_for_exit_signal()   receive()
    send(chunk)            |                    |                      |
      |                    |             event.wait() returns          |
      |                    |                    |                      |
      |                    |             shutdown_event.set()          |
      |                    |              (user event signaled)        |
      |                    |                    |                      |
      |                    |             move_on_after(grace_period)   |
      |                    |              |                            |
      |                    |              +-- while self.active:       |
      |                    |              |     sleep(0.1)             |
      |                    |              |                            |
  [generator sees event]   |              |     (polling...)           |
  yield farewell event     |              |                            |
  return                   |              |                            |
  self.active = False      |              |                            |
  send(more_body=False)    |              |                            |
  return                   |              |                            |
      |                    |              |                            |
  cancel_on_finish -----> CANCEL         CANCEL                  CANCEL
      |
      v
  Clean exit! Farewell event reached client.
```

### Sub-scenario: Generator ignores shutdown_event (grace expires)

```
_stream_response                    _exit_signal_with_grace
      |                                      |
  async for data:                   _listen_for_exit_signal() returns
    send(chunk)                              |
      |                             shutdown_event.set()
      |                                      |
  [generator ignores event,        move_on_after(grace_period)
   keeps yielding]                   |
      |                              +-- while self.active:
      |                              |     sleep(0.1)
      |                              |       ...
      |                              |     (grace_period seconds pass)
      |                              |
      |                              +-- move_on_after EXPIRES
      |                                      |
      |                                    return
      |                                      |
   CANCEL <----------------------- cancel_on_finish
      |
      v
  Generator receives CancelledError (force-cancelled)
```

---

## Flow 5: Send Timeout

```
_stream_response         _ping        _exit_signal    _disconnect
      |                    |               |               |
  async for data:          |               |               |
    move_on_after(timeout):|               |               |
      send(chunk)          |               |               |
        [send hangs!]      |               |               |
           ...             |               |               |
    [timeout expires]      |               |               |
    cancel_called = True   |               |               |
    aclose() iterator      |               |               |
    raise SendTimeoutError |               |               |
      |                    |               |               |
  EXCEPTION propagates through cancel_on_finish into task group
  Task group cancels all siblings
```

---

## Shutdown Detection: Two-Layer Architecture

```
Layer 1: Signal Capture (process-wide)
+------------------------------------------------------------------+
|                                                                  |
|  SIGTERM/SIGINT                                                  |
|       |                                                          |
|       v                                                          |
|  uvicorn.Server.handle_exit()  [monkey-patched at import time]   |
|       |                                                          |
|       v                                                          |
|  AppStatus.should_exit = True                                    |
|  + calls original uvicorn handler                                |
|                                                                  |
|  Fallback (monkey-patch fails, e.g. uvicorn 0.29+):             |
|  _get_uvicorn_server() introspects signal.getsignal(SIGTERM)    |
|  to find uvicorn's Server instance and check .should_exit        |
|                                                                  |
+------------------------------------------------------------------+

Layer 2: Per-Thread Broadcast (thread-local)
+------------------------------------------------------------------+
|                                                                  |
|  Thread A (main event loop)          Thread B (secondary loop)   |
|  +----------------------------+     +------------------------+   |
|  | _thread_state.shutdown_state|     | _thread_state (separate)|  |
|  |   .events = {ev1, ev2, ev3}|     |   .events = {ev4}      |  |
|  |   .watcher_started = True  |     |   .watcher_started=True|  |
|  +----------------------------+     +------------------------+   |
|           |                                   |                  |
|    _shutdown_watcher()                 _shutdown_watcher()       |
|    polls AppStatus.should_exit         polls AppStatus.should_exit|
|    every 0.5s                          every 0.5s                |
|           |                                   |                  |
|    on True: ev1.set()                  on True: ev4.set()        |
|             ev2.set()                                            |
|             ev3.set()                                            |
|                                                                  |
+------------------------------------------------------------------+
```

Each SSE connection registers its own `anyio.Event` with the thread's shutdown state.
One watcher per thread broadcasts to all connections in that thread.

---

## Summary: Who Wins the Race?

| Scenario | Task that returns first | Effect on generator |
|---|---|---|
| Generator exhausted | `_stream_response` | Clean exit, farewell sent |
| Client disconnects | `_listen_for_disconnect` | CancelledError |
| Server shutdown (no grace) | `_listen_for_exit_signal_with_grace` | CancelledError |
| Server shutdown (with grace, generator cooperates) | `_stream_response` | Clean exit, farewell sent |
| Server shutdown (with grace, generator ignores) | `_listen_for_exit_signal_with_grace` (after timeout) | CancelledError |
| Send timeout | `_stream_response` (via exception) | SendTimeoutError |
| Client disconnect during grace | `_listen_for_disconnect` | Grace period cut short |
