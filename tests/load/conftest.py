"""
Pytest fixtures for load testing.

Provides container-based SSE server and utility fixtures.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import httpx
import pytest
from testcontainers.core.container import DockerContainer

from .baseline import BaselineManager
from .metrics import MetricsCollector
from .reporter import ReportGenerator

if TYPE_CHECKING:
    from .metrics import TestReport


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
        "--output-dir",
        action="store",
        default="tests/load/results",
        help="Directory for test reports",
    )
    parser.addoption(
        "--baselines-dir",
        action="store",
        default="tests/load/baselines",
        help="Directory for baseline files",
    )
    parser.addoption(
        "--update-baseline",
        action="store_true",
        default=False,
        help="Save current run as new baseline",
    )
    parser.addoption(
        "--fail-on-regression",
        action="store_true",
        default=False,
        help="Exit non-zero if regression detected",
    )
    parser.addoption(
        "--regression-threshold",
        action="store",
        type=int,
        default=20,
        help="Percent change to trigger regression warning",
    )


@pytest.fixture
def output_dir(request: pytest.FixtureRequest) -> Path:
    """Get the output directory for reports."""
    return Path(request.config.getoption("--output-dir"))


@pytest.fixture
def baselines_dir(request: pytest.FixtureRequest) -> Path:
    """Get the baselines directory."""
    return Path(request.config.getoption("--baselines-dir"))


@pytest.fixture
def update_baseline(request: pytest.FixtureRequest) -> bool:
    """Whether to update baselines."""
    return bool(request.config.getoption("--update-baseline"))


@pytest.fixture
def fail_on_regression(request: pytest.FixtureRequest) -> bool:
    """Whether to fail on regression."""
    return bool(request.config.getoption("--fail-on-regression"))


@pytest.fixture
def metrics_collector() -> MetricsCollector:
    """Fresh metrics collector for each test."""
    return MetricsCollector()


@pytest.fixture(scope="session")
def baseline_manager(request: pytest.FixtureRequest) -> BaselineManager:
    """Baseline manager for comparison."""
    baselines_dir = Path(request.config.getoption("--baselines-dir"))
    threshold = int(request.config.getoption("--regression-threshold"))
    thresholds = {
        "latency_p99_warning_pct": float(threshold),
        "latency_p99_fail_pct": float(threshold * 2.5),
        "throughput_warning_pct": float(-threshold),
        "memory_growth_warning_pct": float(threshold * 2.5),
        "memory_slope_fail": 0.1,
        "error_rate_fail_pct": 5.0,
    }
    return BaselineManager(baselines_dir=baselines_dir, thresholds=thresholds)


@pytest.fixture(scope="session")
def report_generator(request: pytest.FixtureRequest) -> ReportGenerator:
    """Report generator for output."""
    output_dir = Path(request.config.getoption("--output-dir"))
    return ReportGenerator(output_dir=output_dir)


# Store test reports for session-level access
_test_reports: dict[str, "TestReport"] = {}


def pytest_sessionstart(session: pytest.Session) -> None:
    """Clear reports at session start."""
    _test_reports.clear()


def register_test_report(report: "TestReport") -> None:
    """Register a test report for later processing."""
    _test_reports[report.test_name] = report


def get_test_reports() -> dict[str, "TestReport"]:
    """Get all registered test reports."""
    return _test_reports.copy()
