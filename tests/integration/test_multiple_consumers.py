# test_main.py
import asyncio
import logging
import os
import subprocess
import threading
import time

import httpcore
import httpx
import psutil
import pytest

_log = logging.getLogger(__name__)

URL = "http://localhost:8001/endless"
PORT = 8001
LOG_LEVEL = "info"


def run_server():
    # noinspection PyGlobalUndefined
    global server_process
    server_command = f"uvicorn tests.integration.main_endless:app --host localhost --port {PORT} --log-level {LOG_LEVEL}"
    server_process = subprocess.Popen(server_command, shell=True)


def run_server_conditional():
    # noinspection PyGlobalUndefined
    global server_process
    server_command = f"uvicorn tests.integration.main_endless_conditional:app --host localhost --port {PORT} --log-level {LOG_LEVEL}"
    server_process = subprocess.Popen(server_command, shell=True)


def run_asyncio_loop_non_blocking(loop):
    """Run an asyncio client consumer in a separate thread, non-blocking."""

    def run_loop():
        _log.debug(f"run_asyncio_loop {loop=}")
        asyncio.set_event_loop(loop)
        loop.run_until_complete(make_arequest(URL))
        _log.debug(f"ending run_asyncio_loop {loop=}")
        loop.close()

    thread = threading.Thread(target=run_loop)
    thread.start()


async def make_arequest(url):
    """Stream the SSE endpoint, and count the number of lines received."""
    _log.info(f"make_arequest {url=}")
    i = 0
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("GET", url) as response:
                async for line in response.aiter_lines():
                    print(f"{i=}, {line=}")
                    i += 1
        except httpx.RemoteProtocolError as e:
            _log.error(e)
        except httpcore.RemoteProtocolError as e:
            _log.error(e)

        _log.info(f"make_arequest {url=} finished: {i=}")
        assert (
            i == 8
        ), "Expected 8 lines"  # not part of test runner, failure is not reported


@pytest.mark.skipif(os.name == "nt", reason="Skip on Windows")
def test_stop_server_with_many_consumers(caplog):
    """Expect all consumers to close gracefully when the server is stopped."""
    caplog.set_level(logging.DEBUG)
    N_CONSUMER = 3

    # Given: a running server in first thread
    server_thread = threading.Thread(target=run_server)
    server_thread.start()
    time.sleep(1)  # wait for server to start

    # Given: N_CONSUMER consumers in separate threads
    loops = [asyncio.new_event_loop() for _ in range(N_CONSUMER)]
    for loop in loops:
        run_asyncio_loop_non_blocking(loop)

    # When: the server is stopped
    time.sleep(1)
    _log.info(f"terminating {server_process.pid=}")
    # Killing child processes
    parent = psutil.Process(server_process.pid)
    for child in parent.children(recursive=True):
        child.kill()
    parent.kill()
    server_thread.join()
    time.sleep(0.2)  # allow to populate the caplog records

    # Then: all consumers should close gracefully
    # consumers: 'peer closed connection without sending complete message body (incomplete chunked read)'
    errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == N_CONSUMER, f"Expected {N_CONSUMER} errors, got {len(errors)}"


@pytest.mark.skipif(os.name == "nt", reason="Skip on Windows")
def test_stop_server_conditional(caplog):
    """Expect all consumers to close gracefully when the server is stopped."""
    caplog.set_level(logging.DEBUG)
    N_CONSUMER = 1

    # Given: a running server in first thread
    server_thread = threading.Thread(target=run_server_conditional)
    server_thread.start()
    time.sleep(1)  # wait for server to start

    # Given: N_CONSUMER consumers in separate threads
    loops = [asyncio.new_event_loop() for _ in range(N_CONSUMER)]
    for loop in loops:
        run_asyncio_loop_non_blocking(loop)

    # When: the server is stopped
    time.sleep(1)
    _log.info(f"terminating {server_process.pid=}")
    # Killing child processes
    parent = psutil.Process(server_process.pid)
    for child in parent.children(recursive=True):
        child.kill()
    parent.kill()
    server_thread.join()
    time.sleep(0.2)  # allow to populate the caplog records

    # Then: all consumers should close gracefully
    # consumers: 'peer closed connection without sending complete message body (incomplete chunked read)'
    errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == N_CONSUMER, f"Expected {N_CONSUMER} errors, got {len(errors)}"
