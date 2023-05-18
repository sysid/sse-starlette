# Smoke and Integration tests

## Integration test for lost client connection:

1. start example.py with log_level='trace'
2. curl http://localhost:8000/endless
3. kill curl

### expected outcome:
all streaming stops, including pings (log output)


## Integration test for uvicorn shutdown (Ctrl-C) with long running task
1. start example.py with log_level='trace'
2. curl http://localhost:8000/endless from multiple clients/terminals
3. CTRL-C: stop server

### expected outcome:
1. server shut down gracefully, no pending tasks
2. all clients stop (transfer closed with outstanding read data remaining)
