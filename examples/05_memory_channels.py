# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "sse-starlette",
#   "uvicorn",
# ]
# ///
"""
Memory channels as an alternative to async generators for SSE streaming.

This example demonstrates:
- Using anyio memory channels with ``data_sender_callable``
- Producer-consumer pattern decoupling data production from SSE delivery
- Multiple producers feeding a single SSE stream
- Backpressure handling with bounded buffers

Usage:
    python examples/05_memory_channels.py

Test with curl:
    # Single producer (9 items then completes)
    curl -N http://localhost:8000/memory-channel

    # Multiple producers merged into one stream
    curl -N http://localhost:8000/multi-producer

    # Backpressure demo (fast producer, small buffer)
    curl -N http://localhost:8000/backpressure
"""

import asyncio
from functools import partial

import anyio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from sse_starlette import EventSourceResponse


async def data_producer(send_channel: anyio.abc.ObjectSendStream, producer_id: str):
    """
    Producer that generates data and sends it through a memory channel.
    This runs independently of the SSE connection.
    """
    async with send_channel:
        try:
            for i in range(1, 10):
                await asyncio.sleep(1)
                event_data = {
                    "data": f"Data from producer {producer_id}, item {i}",
                    "id": f"{producer_id}-{i}",
                    "event": "production_data",
                }
                await send_channel.send(event_data)

            await send_channel.send(
                {
                    "data": f"Producer {producer_id} completed",
                    "event": "producer_complete",
                }
            )

        except Exception as e:
            await send_channel.send({"data": f"Producer error: {e}", "event": "error"})


async def memory_channel_endpoint(request: Request):
    """SSE endpoint using memory channels instead of generators."""
    send_channel, receive_channel = anyio.create_memory_object_stream(
        max_buffer_size=10
    )
    producer_id = f"prod-{id(request)}"

    return EventSourceResponse(
        receive_channel,
        data_sender_callable=partial(data_producer, send_channel, producer_id),
        ping=5,
    )


async def multi_producer_endpoint(request: Request):
    """Multiple producers feeding one SSE stream via memory channels."""
    combined_send, combined_receive = anyio.create_memory_object_stream(
        max_buffer_size=20
    )

    async def multi_producer_coordinator(combined_channel):
        """Coordinates multiple producers and merges their output."""
        async with combined_channel:
            try:
                producer_channels = []
                for i in range(3):
                    send_ch, recv_ch = anyio.create_memory_object_stream(
                        max_buffer_size=5
                    )
                    producer_channels.append((send_ch, recv_ch, f"multi-{i}"))

                async with anyio.create_task_group() as tg:
                    for send_ch, _, prod_id in producer_channels:
                        tg.start_soon(data_producer, send_ch, prod_id)

                    async def merge_outputs():
                        receive_channels = [
                            recv_ch for _, recv_ch, _ in producer_channels
                        ]
                        async with anyio.create_task_group() as merge_tg:
                            for recv_ch in receive_channels:
                                merge_tg.start_soon(
                                    forward_channel_data, recv_ch, combined_channel
                                )

                    tg.start_soon(merge_outputs)

            except Exception as e:
                await combined_channel.send(
                    {"data": f"Multi-producer error: {e}", "event": "error"}
                )

    return EventSourceResponse(
        combined_receive,
        data_sender_callable=partial(multi_producer_coordinator, combined_send),
        ping=3,
    )


async def forward_channel_data(source_channel, target_channel):
    """Forward data from one channel to another."""
    async with source_channel:
        async for item in source_channel:
            try:
                await target_channel.send(item)
            except anyio.BrokenResourceError:
                break


async def backpressure_demo_endpoint(request: Request):
    """Demonstrates backpressure handling with a small bounded buffer."""
    send_channel, receive_channel = anyio.create_memory_object_stream(max_buffer_size=2)

    async def fast_producer(channel):
        """Producer that generates data faster than typical consumption."""
        async with channel:
            try:
                for i in range(20):
                    event_data = {
                        "data": f"Fast data {i} - buffer may be full!",
                        "id": str(i),
                        "event": "fast_data",
                    }
                    # This will block when buffer is full (backpressure)
                    await channel.send(event_data)
                    await asyncio.sleep(0.01)

            except Exception as e:
                await channel.send({"data": f"Producer error: {e}", "event": "error"})

    return EventSourceResponse(
        receive_channel,
        data_sender_callable=partial(fast_producer, send_channel),
        ping=2,
    )


app = Starlette(
    routes=[
        Route("/memory-channel", memory_channel_endpoint),
        Route("/multi-producer", multi_producer_endpoint),
        Route("/backpressure", backpressure_demo_endpoint),
    ]
)

if __name__ == "__main__":
    import uvicorn

    print("Starting memory channels SSE server...")
    print("Available endpoints:")
    print("  - http://localhost:8000/memory-channel (single producer-consumer)")
    print("  - http://localhost:8000/multi-producer (3 producers, one stream)")
    print("  - http://localhost:8000/backpressure (backpressure demo)")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
