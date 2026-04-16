"""
Test utilities and fixtures for the orchestrator test suite.
"""

import pytest
import pytest_asyncio
import logging

try:
    from config import LLMConfig
except ImportError:
    from config import LLMConfig

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def llm_config():
    """Fixture providing a test LLM configuration."""
    return LLMConfig(
        base_url="http://127.0.0.1:8000/v1",
        model="test-model",
        temperature=1.0,
        top_p=0.95,
        top_k=64
    )


@pytest_asyncio.fixture
async def mock_llm_responses():
    """Fixture providing common mock LLM responses."""
    return {
        "simple_response": {
            "choices": [
                {
                    "message": {
                        "content": "This is a simple response.",
                        "tool_calls": []
                    }
                }
            ]
        },
        "with_tool_call": {
            "choices": [
                {
                    "message": {
                        "content": "Let me execute a tool.",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/test.txt"}'
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }


@pytest_asyncio.fixture
async def mock_mcp_tools():
    """Fixture providing common mock MCP tools."""
    return {
        "read_file": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the filesystem",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        "write_file": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        "list_directory": {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List directory contents",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"}
                    },
                    "required": ["path"]
                }
            }
        }
    }


@pytest.fixture
def caplog_setup():
    """Setup for capturing logs during tests."""
    logging.getLogger("orchestrator").setLevel(logging.DEBUG)
    logging.getLogger("llm_adapter").setLevel(logging.DEBUG)
    logging.getLogger("mcp_orchestrator").setLevel(logging.DEBUG)
    logging.getLogger("agent_loop").setLevel(logging.DEBUG)
