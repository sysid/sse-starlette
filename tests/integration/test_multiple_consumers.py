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


def run_asyncio_loop_non_blocking(loop, expected_lines=2) -> threading.Thread:
    """Run an asyncio client consumer in a separate thread, non-blocking."""

    def run_loop():
        _log.debug(
            f"{threading.current_thread().ident}: run_asyncio_loop {loop=}, {expected_lines=}"
        )
        asyncio.set_event_loop(loop)
        loop.run_until_complete(make_arequest(URL, expected_lines=expected_lines))
        _log.debug(
            f"{threading.current_thread().ident}: ending run_asyncio_loop {loop=}"
        )  # not reached (server streaming endless)
        loop.close()

    thread = threading.Thread(target=run_loop)
    thread.start()
    return thread


async def make_arequest(url, expected_lines=2):
    """Simulate Client:
    Stream the SSE endpoint, and count the number of lines received.
    """
    _log.info(f"{threading.current_thread().ident}: make_arequest {url=}")
    i = 0
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("GET", url) as response:
                async for line in response.aiter_lines():
                    print(f"{threading.current_thread().ident}: {i=}, {line=}")
                    i += 1
        except httpx.RemoteProtocolError as e:
            _log.error(e)
        except httpcore.RemoteProtocolError as e:
            _log.error(e)

        _log.info(
            f"{threading.current_thread().ident}: make_arequest {url=} finished: {i=}"
        )
        # lines to expect:
        # i=0, line='data: u can haz the data'
        # i=1, line=''
        assert (
            i == expected_lines
        ), f"Expected {expected_lines} lines"  # not part of test runner, failure is not reported


@pytest.mark.skipif(os.name == "nt", reason="Skip on Windows")
# @pytest.mark.skip
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
    threads = [run_asyncio_loop_non_blocking(loop, expected_lines=8) for loop in loops]
    # for loop in loops:
    #     run_asyncio_loop_non_blocking(loop)

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

    for loop in loops:
        if not loop.is_closed():
            loop.close()
    for thread in threads:
        thread.join()  # Wait for the thread to finish
    # time.sleep(0.2)
    # assert len(threading.enumerate()) == 1  # Only the main thread should remain


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
    threads = [run_asyncio_loop_non_blocking(loop, expected_lines=2) for loop in loops]

    time.sleep(0.5)  # TODO: Error message only triggered for <=5 seconds, why?

    # When: the server is stopped
    _log.info(f"terminating {server_process.pid=}")
    # Killing child processes
    parent = psutil.Process(server_process.pid)
    for child in parent.children(recursive=True):
        child.kill()
    parent.kill()
    server_thread.join()
    time.sleep(0.2)  # allow to populate the caplog records

    # Then: all consumers should close gracefully
    # expected error-message from consumers:
    # 'peer closed connection without sending complete message body (incomplete chunked read)'
    errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
    _log.info(f"{errors=}")
    assert all(
        "peer closed connection without sending complete message" in message
        for message in errors
    ), "Not all messages contain the required substring!"

    # Then: one consumer, so one error-message
    assert len(errors) == N_CONSUMER, f"Expected {N_CONSUMER} errors, got {len(errors)}"

    for loop in loops:
        if not loop.is_closed():
            loop.close()
    for thread in threads:
        thread.join()  # Wait for the thread to finish
