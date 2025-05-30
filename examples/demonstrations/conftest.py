# tests/test_sse.py (UNCHANGED - Keep existing unit tests)
# tests/test_event.py (UNCHANGED - Keep existing unit tests)
# tests/conftest.py (UNCHANGED - Keep existing fixtures)

# Remove these files (move content to demonstrations/):
# - tests/integration/test_multiple_consumers.py
# - tests/experimentation/test_multiple_consumers_threads.py
# - tests/experimentation/test_multiple_consumers_asyncio.py

# demonstrations/README.md
"""
# SSE Educational Demonstrations

This directory contains focused, educational demonstrations of SSE patterns and behaviors.
Each demonstration shows ONE key concept clearly without unnecessary complexity.

## Philosophy

These are **educational scenarios**, not traditional unit tests. They demonstrate:
- Real-world SSE patterns and behaviors
- Common production challenges and solutions
- Best practices through working examples
- Edge cases and error conditions

## Directory Structure

### 📁 basic_patterns/
**Purpose**: Core SSE behaviors every developer should understand

- **graceful_shutdown.py**: Server shutdown behavior and cleanup patterns
- **client_disconnect.py**: Client disconnection detection and resource cleanup

**Key Learning**: SSE connection lifecycle, resource management, proper cleanup

### 📁 production_scenarios/
**Purpose**: Real-world deployment patterns and challenges

- **load_simulation.py**: Multiple concurrent clients and performance testing
- **network_interruption.py**: Handling network failures and reconnection

**Key Learning**: Production readiness, scalability, resilience patterns

### 📁 advanced_patterns/
**Purpose**: Sophisticated streaming techniques and architectures

- **memory_channels.py**: Using memory channels instead of generators
- **error_recovery.py**: Comprehensive error handling and recovery strategies
- **custom_protocols.py**: Building domain-specific protocols over SSE

**Key Learning**: Advanced architectures, error resilience, protocol design

## Running Demonstrations

Each file is self-contained and executable:

```bash
# Basic patterns
python demonstrations/basic_patterns/multiple_clients.py
python demonstrations/basic_patterns/graceful_shutdown.py
python demonstrations/basic_patterns/client_disconnect.py

# Production scenarios
python demonstrations/production_scenarios/load_simulation.py test 20
python demonstrations/production_scenarios/network_interruption.py demo

# Advanced patterns
python demonstrations/advanced_patterns/memory_channels.py
python demonstrations/advanced_patterns/error_recovery.py
python demonstrations/advanced_patterns/custom_protocols.py
```

## Educational Progression

### 🎯 Level 1: Basic Understanding
Start with `basic_patterns/` to understand:
- How SSE connections work
- Client-server lifecycle
- Resource cleanup importance

### 🎯 Level 2: Production Readiness
Continue with `production_scenarios/` to learn:
- Deployment considerations
- Performance characteristics
- Network resilience

### 🎯 Level 3: Advanced Techniques
Explore `advanced_patterns/` for:
- Sophisticated architectures
- Error handling strategies
- Custom protocol design

## Key Learning Outcomes

After working through these demonstrations, you'll understand:

1. **SSE Connection Lifecycle**
   - How connections are established and maintained
   - What happens during client disconnections
   - Proper resource cleanup patterns

2. **Production Deployment**
   - Container-based testing approaches
   - Performance and scalability considerations
   - Network failure handling

3. **Advanced Architectures**
   - When to use memory channels vs generators
   - Error recovery and circuit breaker patterns
   - Building custom protocols over SSE

## Design Principles

Each demonstration follows these principles:

### ✅ **Focused Learning**
- ONE key concept per demonstration
- No unnecessary complexity or features
- Clear learning objectives stated upfront

### ✅ **Production Relevant**
- Patterns used in real applications
- Common problems and solutions
- Best practices embedded in code

### ✅ **Self-Contained**
- Each demo runs independently
- No external dependencies beyond the project
- Complete working examples

### ✅ **Educational Comments**
- Rich comments explaining WHY, not just WHAT
- Design decisions explained
- Alternative approaches discussed

## Testing vs Demonstrations

**Traditional Tests (`tests/`)**:
- Verify correctness of implementation
- Fast execution, isolated units
- Assert specific behaviors
- Part of CI/CD pipeline

**Educational Demonstrations (`demonstrations/`)**:
- Show real-world usage patterns
- May be slow, interactive
- Demonstrate behaviors visually
- Learning and reference tools

## Integration with CI/CD

While demonstrations are primarily educational, they can be integrated into CI:

```bash
# Run basic smoke tests on demonstrations
python -m pytest demonstrations/ -k "test_" --timeout=30

# Or run as integration tests
make demo-test
```

## Contributing New Demonstrations

When adding new demonstrations:

1. **Choose the right category** (basic/production/advanced)
2. **Focus on ONE key concept** per file
3. **Add rich educational comments** explaining the WHY
4. **Make it self-contained** and executable
5. **Update this README** with the new demonstration

## Common Questions

**Q: Why separate from regular tests?**
A: Demonstrations focus on education and real-world patterns, while tests verify correctness. Different purposes, different approaches.

**Q: How long should demonstrations take to run?**
A: Basic patterns: 10-30 seconds. Production scenarios: 30-60 seconds. Advanced patterns: 30-120 seconds.

**Q: Can I use these in production?**
A: These are educational examples. Extract patterns and adapt for your specific use case.

**Q: How do I know which demonstration to run first?**
A: Start with basic_patterns/, then production_scenarios/, then advanced_patterns/. Each builds on the previous level.
"""

# demonstrations/conftest.py
"""
Shared fixtures and utilities for demonstrations.
Kept minimal to avoid complexity.
"""

import pytest
import asyncio
from typing import AsyncGenerator
import httpx


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for demonstration testing."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


@pytest.fixture
def demo_server_url() -> str:
    """Base URL for demonstration servers."""
    return "http://localhost:8000"
