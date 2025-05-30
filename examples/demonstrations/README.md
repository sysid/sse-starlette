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
