"""
Pytest fixtures for load testing.

Provides container-based SSE server and utility fixtures.
"""

import os
import time
from typing import Generator

import httpx
import pytest
from testcontainers.core.container import DockerContainer


class SSELoadTestContainer(DockerContainer):
    """Custom container for SSE load testing."""

    def __init__(self, image: str = "sse-starlette-loadtest:latest"):
        super().__init__(image)
        self.with_exposed_ports(8000)

    def get_base_url(self) -> str:
        """Get the base URL for the SSE server."""
        host = self.get_container_host_ip()
        port = self.get_exposed_port(8000)
        return f"http://{host}:{port}"


def _wait_for_port(container: DockerContainer, port: int, timeout: float = 30) -> str:
    """Wait for port mapping to be available and return base URL."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            host = container.get_container_host_ip()
            mapped_port = container.get_exposed_port(port)
            return f"http://{host}:{mapped_port}"
        except ConnectionError:
            time.sleep(0.5)
    raise TimeoutError(f"Port {port} not available after {timeout}s")


def _wait_for_health(base_url: str, timeout: float = 30) -> None:
    """Wait for server health endpoint to respond."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2.0)
            if resp.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Server at {base_url} not ready after {timeout}s")


@pytest.fixture(scope="module")
def docker_available() -> bool:
    """Check if Docker is available."""
    return os.path.exists("/var/run/docker.sock")


@pytest.fixture(scope="module")
def sse_container(
    docker_available: bool,
) -> Generator[SSELoadTestContainer, None, None]:
    """Start SSE server in Docker container for load testing."""
    if not docker_available:
        pytest.skip("Docker not available")

    container = SSELoadTestContainer()
    container.start()

    # Wait for port mapping, then health check
    base_url = _wait_for_port(container, 8000, timeout=30)
    _wait_for_health(base_url, timeout=30)

    yield container

    container.stop()


@pytest.fixture(scope="module")
def sse_server_url(sse_container: SSELoadTestContainer) -> str:
    """Get the base URL for the SSE server."""
    return sse_container.get_base_url()


@pytest.fixture
def sync_client() -> Generator[httpx.Client, None, None]:
    """Synchronous HTTP client for simple requests."""
    with httpx.Client(timeout=30.0) as client:
        yield client


@pytest.fixture
async def async_client() -> httpx.AsyncClient:
    """Async HTTP client for SSE streaming."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options for load tests."""
    parser.addoption(
        "--scale",
        action="store",
        default="100",
        help="Number of concurrent connections for load tests",
    )
    parser.addoption(
        "--duration",
        action="store",
        default="1",
        help="Test duration in minutes",
    )


@pytest.fixture
def scale(request: pytest.FixtureRequest) -> int:
    """Get the scale (number of connections) for load tests."""
    return int(request.config.getoption("--scale"))


@pytest.fixture
def duration_minutes(request: pytest.FixtureRequest) -> int:
    """Get the duration in minutes for load tests."""
    return int(request.config.getoption("--duration"))
