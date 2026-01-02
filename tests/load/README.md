# SSE-Starlette Load Tests

Performance and stability tests for the SSE implementation under realistic load conditions.

## Overview

These tests measure performance characteristics that unit tests cannot capture:
- Throughput under concurrent load
- Memory stability over time
- Resource cleanup after disconnections
- Graceful shutdown behavior
- Backpressure handling

## Quick Start

```bash
# Run load tests locally (requires Docker)
make test-load

# Update baselines after intentional changes
make test-load PYTEST_ARGS="--update-baseline"
```

## Architecture

```
tests/load/
├── conftest.py          # Fixtures, CLI options, Docker container setup
├── metrics.py           # MetricsCollector, statistics computation
├── baseline.py          # BaselineManager, regression detection
├── reporter.py          # JSON + HTML report generation
├── server_app.py        # Test server with /sse and /metrics endpoints
├── Dockerfile.loadtest  # Container for isolated server testing
├── baselines/           # Git-tracked baseline files (*.json)
├── results/             # Generated reports (gitignored)
└── test_*.py            # Test modules
```

## KPI Persistence & Baselining

### How It Works

1. **During Test Run**: `MetricsCollector` aggregates samples (latencies, memory, events)
2. **After Test**: Statistics computed (p50/p95/p99, mean, stdev, slopes)
3. **Report Generation**: JSON file saved to `tests/load/results/<test_name>.json`
4. **Baseline Comparison**: Current run compared against `tests/load/baselines/<test_name>.json`
5. **Regression Detection**: Percent changes flagged if exceeding thresholds

### Baseline Files

Baselines are **git-tracked** so changes are visible in PRs:

```
tests/load/baselines/
├── test_throughput_single_client.json
├── test_memory_stability_under_load.json
└── ...
```

Each baseline contains:
```json
{
  "test_name": "test_throughput_single_client",
  "timestamp": "2024-01-15T14:30:00Z",
  "git_commit": "abc1234",
  "throughput": {
    "aggregate_events_per_sec": 12456.7,
    "per_client_events_per_sec": [12456.7]
  },
  "latency": { "p50_ms": 14.8, "p95_ms": 21.4, "p99_ms": 27.4 },
  "memory": { "baseline_mb": 45.2, "peak_mb": 67.8, "growth_mb": 22.6 }
}
```

### Updating Baselines

```bash
# After intentional performance changes (optimization, new features)
make test-load PYTEST_ARGS="--update-baseline"

# Then commit the updated baseline files
git add tests/load/baselines/
git commit -m "Update load test baselines after optimization"
```

### Regression Detection

| Metric | Warning Threshold | Fail Threshold |
|--------|-------------------|----------------|
| Latency p99 | +20% | +50% |
| Throughput | -20% | - |
| Memory growth | +50% | - |
| Memory slope | - | >0.1 MB/sec |
| Error rate | - | >5% |

Enable in CI:
```bash
make test-load PYTEST_ARGS="--fail-on-regression"
```

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output-dir` | `tests/load/results` | Report output directory |
| `--baselines-dir` | `tests/load/baselines` | Baseline file directory |
| `--update-baseline` | False | Save current run as new baseline |
| `--fail-on-regression` | False | Exit non-zero if regression detected |
| `--regression-threshold` | 20 | Percent change to trigger warning |

**Note**: Test scale (connections, duration) is controlled via constants within each test file.
This allows appropriate parameters per test type (e.g., shutdown tests use fewer connections).

## Test Categories

### Throughput (`test_throughput.py`)
- Single client maximum throughput (baseline without contention)
- Multi-client aggregate throughput (scaling behavior)
- Time to first event (connection setup latency)
- Inter-event latency under load (backpressure detection)

### Memory Stability (`test_memory_stability.py`)
- Memory growth during sustained streaming
- Memory reclamation after disconnect
- Event set cleanup (Issue #152 regression)

### Watcher Scale (`test_watcher_scale.py`)
- Single watcher with many connections (Issue #152 core test)
- Watcher stability under rapid churn
- Watcher lifecycle (start → broadcast → cleanup → restart)

### Shutdown (`test_shutdown.py`)
- Graceful shutdown timing with active connections
- Shutdown signal propagation to streams

### Backpressure (`test_backpressure.py`)
- Slow client isolation (fast clients unaffected)
- Resource stability under connection churn
- send_timeout behavior with frozen clients

## Limitations: What These Tests Don't Cover

### Not Measured

1. **True Production Scale**
   - Tests run at 100-1000 connections; production may see 10K+
   - Resource contention patterns differ at extreme scale
   - OS-level limits (ulimit, ephemeral ports) not tested

2. **Network Conditions**
   - Tests run on localhost/Docker bridge
   - No simulation of latency, packet loss, or bandwidth limits
   - Real network jitter not captured

3. **Long-Running Stability**
   - Tests run for minutes; production runs for days/weeks
   - Slow leaks (bytes/hour) may not appear in short tests
   - GC pressure patterns differ over extended periods

4. **CPU Profiling**
   - No measurement of CPU cycles per event
   - Hot path optimization regressions not detected
   - Async scheduler overhead not isolated

5. **Multi-Process/Multi-Node**
   - Tests run single uvicorn process
   - No testing of gunicorn worker coordination
   - No distributed load balancer behavior

6. **Client Diversity**
   - All clients use httpx (same HTTP/1.1 implementation)
   - No HTTP/2 or HTTP/3 testing
   - No browser-specific SSE behavior (reconnection, Last-Event-ID)

7. **Garbage Collection Impact**
   - Python GC pauses not isolated
   - Memory pressure from other processes not simulated
   - Different GC generations not separately measured

### Potential Blind Spots

| Regression Type | Detection Gap |
|-----------------|---------------|
| 5% throughput drop | Below noise floor |
| Sub-millisecond latency spikes | Averaged out in percentiles |
| Memory leak < 1KB/connection | Too slow to appear in test duration |
| CPU regression without throughput impact | Not measured |
| Thread pool exhaustion at >1000 connections | Scale not tested |
| Event loop blocking < 10ms | Within jitter tolerance |

### Recommendations for Production

1. **APM Integration**: Use Datadog/NewRelic for continuous production metrics
2. **Synthetic Monitoring**: Run periodic load tests against staging
3. **Canary Deployments**: Compare metrics between old/new versions
4. **Memory Profiling**: Run tracemalloc in staging for leak detection
5. **CPU Profiling**: Use py-spy periodically to catch hot path regressions

## Report Outputs

### JSON Report
Full structured data for programmatic analysis:
```
tests/load/results/test_throughput_single_client.json
```

### HTML Report
Self-contained visualization with inline SVG charts:
```
tests/load/results/test_throughput_single_client.html
```

Features:
- Summary metrics table
- Memory usage over time chart
- Latency distribution (when applicable)
- Comparison against baseline with delta percentages
- Regression/warning highlights

## Server Metrics Endpoint

The load test server exposes `/metrics` for monitoring:

```json
{
  "memory_rss_mb": 45.2,
  "num_fds": 25,
  "num_threads": 8,
  "watcher_started": true,
  "registered_events": 100,
  "uptime_seconds": 30.5
}
```

Key metrics:
- `memory_rss_mb`: Detect memory leaks
- `registered_events`: Verify Issue #152 (should equal active connections)
- `watcher_started`: Confirm single watcher pattern
- `num_fds`: Detect file descriptor leaks

## Dependencies

Added to `pyproject.toml` as optional `[loadtest]` group:

```bash
pip install -e ".[loadtest]"
```

## GitHub Actions Integration

The workflow (`.github/workflows/load-test.yml`) supports:
- Manual trigger via workflow_dispatch
- Baseline update option
- Regression detection for CI gates
- Artifact upload for reports

## Design Decisions

| Choice | Rationale |
|--------|-----------|
| httpx-sse + asyncio | Native async SSE client, simple concurrency with asyncio.gather() |
| Docker containers | Isolated environment, reproducible, clean SIGTERM shutdown |
| Manual CI trigger | Load tests are resource-intensive, not suitable for every PR |
| psutil for metrics | Cross-platform, no infrastructure needed, real-time data |
