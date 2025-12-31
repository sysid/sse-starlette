# demonstrations/advanced_patterns/memory_channels.py
"""
DEMONSTRATION: Memory Channels Alternative to Generators

PURPOSE:
Shows how to use anyio memory channels instead of async generators
for SSE streaming, providing better control over data flow.

KEY LEARNING:
- Memory channels decouple data production from consumption
- Better error handling and resource management
- More flexible than generators for complex scenarios

PATTERN:
Producer-consumer pattern using memory channels for SSE.
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
    async with send_channel:  # Ensures channel closes when done
        try:
            print(f"🏭 Producer {producer_id} started")

            for i in range(1, 10):
                # Simulate data processing
                await asyncio.sleep(1)

                # Create event data
                event_data = {
                    "data": f"Data from producer {producer_id}, item {i}",
                    "id": f"{producer_id}-{i}",
                    "event": "production_data",
                }

                # Send through channel (non-blocking)
                await send_channel.send(event_data)
                print(f"📤 Producer {producer_id} sent item {i}")

            # Send completion signal
            await send_channel.send(
                {
                    "data": f"Producer {producer_id} completed",
                    "event": "producer_complete",
                }
            )

        except Exception as e:
            print(f"💥 Producer {producer_id} error: {e}")
            # Send error through channel
            await send_channel.send({"data": f"Producer error: {e}", "event": "error"})

        finally:
            print(f"🧹 Producer {producer_id} cleanup completed")


async def memory_channel_endpoint(request: Request):
    """
    SSE endpoint using memory channels instead of generators.
    """
    # Create memory channel for producer-consumer communication
    send_channel, receive_channel = anyio.create_memory_object_stream(
        max_buffer_size=10  # Bounded buffer prevents memory issues
    )

    # Create unique producer ID for this connection
    producer_id = f"prod-{id(request)}"

    # Create EventSourceResponse with channel and producer
    return EventSourceResponse(
        receive_channel,  # Consumer side of the channel
        data_sender_callable=partial(data_producer, send_channel, producer_id),
        ping=5,
    )


async def multi_producer_endpoint(request: Request):
    """
    Advanced example: Multiple producers feeding one SSE stream.
    Demonstrates how memory channels enable complex data flows.
    """
    # Create channel for combined output
    combined_send, combined_receive = anyio.create_memory_object_stream(
        max_buffer_size=20
    )

    async def multi_producer_coordinator(combined_channel):
        """
        Coordinates multiple producers and merges their output.
        """
        async with combined_channel:
            try:
                # Create multiple producer channels
                producer_channels = []
                for i in range(3):  # 3 producers
                    send_ch, recv_ch = anyio.create_memory_object_stream(
                        max_buffer_size=5
                    )
                    producer_channels.append((send_ch, recv_ch, f"multi-{i}"))

                async with anyio.create_task_group() as tg:
                    # Start all producers
                    for send_ch, _, prod_id in producer_channels:
                        tg.start_soon(data_producer, send_ch, prod_id)

                    # Merge all producer outputs
                    async def merge_outputs():
                        # Collect all receive channels
                        receive_channels = [
                            recv_ch for _, recv_ch, _ in producer_channels
                        ]

                        # Use anyio to multiplex channels
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
    """
    Helper function to forward data from one channel to another.
    """
    async with source_channel:
        async for item in source_channel:
            try:
                await target_channel.send(item)
            except anyio.BrokenResourceError:
                # Target channel closed
                break


async def backpressure_demo_endpoint(request: Request):
    """
    Demonstrates backpressure handling with memory channels.
    Shows what happens when producer is faster than consumer.
    """
    # Small buffer to demonstrate backpressure
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

                    print(f"🚀 Trying to send item {i}")

                    # This will block when buffer is full (backpressure)
                    await channel.send(event_data)
                    print(f"✅ Sent item {i}")

                    # Producer works faster than typical consumer
                    await asyncio.sleep(0.01)

            except Exception as e:
                print(f"💥 Fast producer error: {e}")
                await channel.send({"data": f"Producer error: {e}", "event": "error"})

    return EventSourceResponse(
        receive_channel,
        data_sender_callable=partial(fast_producer, send_channel),
        ping=2,
    )


# Test application
app = Starlette(
    routes=[
        Route("/memory-channel", memory_channel_endpoint),
        Route("/multi-producer", multi_producer_endpoint),
        Route("/backpressure", backpressure_demo_endpoint),
    ]
)

if __name__ == "__main__":
    """
    DEMONSTRATION STEPS:
    1. Run server: python memory_channels.py
    2. Test single producer: curl -N http://localhost:8000/memory-channel
    3. Test multi-producer: curl -N http://localhost:8000/multi-producer
    4. Test backpressure: curl -N http://localhost:8000/sse | pv -q -L 10

    MEMORY CHANNEL BENEFITS:
    - Better separation of concerns (producer vs consumer)
    - Built-in backpressure handling
    - Multiple producers can feed one stream
    - More robust error handling
    - Easier testing and debugging

    WHEN TO USE:
    - Complex data processing pipelines
    - Multiple data sources
    - Need for buffering and flow control
    - Better error isolation required
    """
    import uvicorn

    print("🚀 Starting memory channels demonstration server...")
    print("📋 Available endpoints:")
    print("   /memory-channel  - Basic producer-consumer pattern")
    print("   /multi-producer  - Multiple producers, one stream")
    print("   /backpressure    - Backpressure demonstration")

    uvicorn.run(app, host="localhost", port=8000, log_level="info")
