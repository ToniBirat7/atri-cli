# Orchestrator Integration Tests

Comprehensive test suite for the Tarbar_AI orchestrator service, covering:

- **Agent Loop:** Agentic AI loop with tool calling, budgeting, and state tracking
- **LLM Adapter:** Tool-call parsing (OpenAI and native Gemma 4 formats)
- **MCP Orchestrator:** Tool execution and error handling
- **Tool Registry:** Tool discovery and schema translation

## Getting Started

### Install Test Dependencies

```bash
cd services/orchestrator
pip install -r tests/requirements-test.txt
```

### Run All Tests

```bash
# Run all tests with verbose output
pytest tests/ -v

# Run with coverage reporting
pytest tests/ --cov=. --cov-report=html

# Run specific test file
pytest tests/test_integration.py -v

# Run specific test class
pytest tests/test_integration.py::TestAgentLoopBasics -v

# Run specific test
pytest tests/test_integration.py::TestAgentLoopBasics::test_agent_loop_no_tools -v
```

### Test Organization

Tests are organized into logical groups using pytest markers:

```bash
# Run only unit tests
pytest tests/ -m unit

# Run only integration tests
pytest tests/ -m integration

# Run only async tests
pytest tests/ -m async

# Run tool-call parsing tests
pytest tests/test_llm_adapter.py -m "openai_parsing or native_parsing"
```

## Test Suites

### 1. Integration Tests (`test_integration.py`)

**TestAgentLoopBasics**
- ✅ No tool calls (simple response)
- ✅ Single tool call execution
- ✅ Parallel tool calls (multiple independent calls)
- ✅ Max turns enforcement
- ✅ Max tool calls per turn enforcement
- ✅ Tool execution error handling
- ✅ Thinking mode (reasoning tokens)
- ✅ State tracking and observability

**TestNativeToolCallParsing**
- Native Gemma 4 `<|tool_call>` format extraction
- Complex argument handling with string delimiters

**TestErrorRecovery**
- Malformed tool input handling
- Network error recovery

### 2. LLM Adapter Tests (`test_llm_adapter.py`)

**TestToolCallParsing**
- ✅ OpenAI format: single tool call
- ✅ OpenAI format: multiple parallel tool calls
- ✅ OpenAI format: no tool calls
- ✅ OpenAI format: complex nested JSON arguments
- ✅ Native Gemma 4 format parsing
- ✅ Native Gemma 4 with string values

**TestToolCallRobustness**
- Malformed JSON arguments
- Missing function names
- Empty tool_calls array
- Missing choices field

**TestToolCallFormatConsistency**
- All parsed tool calls have required fields

### 3. MCP Orchestrator Tests (`test_mcp_orchestrator.py`)

**TestMCPOrchestratorToolExecution**
- Tool execution success
- Tool execution with parameters
- Invalid tool handling
- Invalid server handling
- Timeout handling
- Error response handling

**TestToolRegistry**
- Tool registry to OpenAI format conversion
- Tool registry filtering
- Tool registry caching

## Running Tests with Docker

```bash
# Build orchestrator service with test dependencies
docker build -t tarbar-orchestrator-tests \
  -f Dockerfile.tests \
  .

# Run tests in container
docker run --rm tarbar-orchestrator-tests \
  pytest tests/ -v --cov=.
```

## Performance Benchmarking

```bash
# Run only slow tests
pytest tests/ -m slow -v

# Skip slow tests
pytest tests/ -m "not slow" -v

# Run with timing information
pytest tests/ -v --durations=10
```

## GPU-Specific Tests

Tests that validate GPU acceleration:

```bash
# Run GPU-specific tests (requires CUDA llama-server running)
pytest tests/ -m gpu -v

# These tests include:
# - Token generation speed verification
# - GPU memory utilization checks
# - GPU/CPU hybrid offload validation
```

## Debugging Tests

```bash
# Run with detailed logging
pytest tests/ -v --log-cli-level=DEBUG

# Drop into pdb on test failure
pytest tests/ -v --pdb

# Show print output immediately
pytest tests/ -v -s

# Run single test with maximum verbosity
pytest tests/test_integration.py::TestAgentLoopBasics::test_agent_loop_single_tool_call -vv -s
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Orchestrator Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r services/orchestrator/tests/requirements-test.txt
      - run: pytest services/orchestrator/tests/ -v --cov
```

## Test Coverage Goals

- **Agent Loop:** 90%+ coverage
- **LLM Adapter:** 85%+ coverage (excluding network I/O)
- **MCP Orchestrator:** 80%+ coverage
- **Tool Registry:** 90%+ coverage

View coverage report:

```bash
pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

## Common Issues

### Tests timing out
- Increase timeout in `pytest.ini`: `timeout = 60`
- Run specific tests: `pytest tests/test_integration.py::TestAgentLoopBasics -v`

### Async tests failing
- Verify `pytest-asyncio` is installed: `pip install pytest-asyncio`
- Check `pytest.ini` has `asyncio_mode = auto`

### Import errors
- Ensure you're running pytest from the orchestrator directory or project root
- Add orchestrator to PYTHONPATH: `export PYTHONPATH=$PYTHONPATH:/path/to/orchestrator`

### Mock-related failures
- Verify mock objects implement required interfaces
- Check that mock return values match expected types

## Contributing New Tests

When adding new tests:

1. **Use descriptive names:** `test_agent_loop_recovers_from_tool_failure`
2. **Add docstrings:** Explain what's being tested and why
3. **Use markers:** Tag with appropriate markers (`@pytest.mark.integration`, etc.)
4. **Mock external dependencies:** Don't hit real LLM/MCP services
5. **Test edge cases:** Error conditions, boundary values, malformed input
6. **Follow arrange-act-assert pattern:**
   ```python
   async def test_example(self):
       # Arrange
       loop = AgentLoop()
       llm = MockLLMAdapter()
       
       # Act
       result = await loop.run(...)
       
       # Assert
       assert result.status == "completed"
   ```

## Useful References

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)
- [Agent Loop Implementation](../agent_loop.py)
- [LLM Adapter Implementation](../llm_adapter.py)

---

**Last Updated:** April 16, 2026  
**Gemma 4 Model:** E2B Q4_K_M (Text-only)  
**GPU Support:** CUDA-enabled (RTX 3060, sm_86)
