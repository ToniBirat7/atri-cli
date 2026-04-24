import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, AsyncMock

# Add project root to path so we can import services
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.orchestrator.agent_loop import AgentLoop, TurnOutcome, Turn
from services.orchestrator.llm_adapter import LLMAdapter, ToolCall

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StressTest")

class MockLLMAdapter:
    def __init__(self, scenarios: List[Dict[str, Any]]):
        self.scenarios = scenarios
        self.current_scenario_idx = 0
        self.turn_in_scenario = 0

    async def chat_completion(self, messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        scenario = self.scenarios[self.current_scenario_idx]
        responses = scenario["responses"]
        
        if self.turn_in_scenario >= len(responses):
            # End scenario with a summary
            content = f"Scenario {self.current_scenario_idx} complete."
            tool_calls = None
        else:
            resp = responses[self.turn_in_scenario]
            content = resp.get("content", "Thinking...")
            tool_calls = resp.get("tool_calls")
            self.turn_in_scenario += 1

        choice = {
            "message": {
                "role": "assistant",
                "content": content,
            }
        }
        if tool_calls:
            choice["message"]["tool_calls"] = [
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["input"])
                    }
                } for i, tc in enumerate(tool_calls)
            ]
            choice["finish_reason"] = "tool_calls"
        else:
            choice["finish_reason"] = "stop"

        return {
            "choices": [choice],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}
        }

    async def extract_tool_calls(self, completion: Dict[str, Any]) -> List[ToolCall]:
        choice = completion["choices"][0]
        tcs = choice["message"].get("tool_calls", [])
        return [
            ToolCall(
                id=tc["id"],
                tool_name=tc["function"]["name"],
                tool_input=json.loads(tc["function"]["arguments"])
            ) for tc in tcs
        ]

    def format_tool_result(self, name: str, result: str, call_id: str) -> Dict[str, str]:
        return {"role": "tool", "content": result, "tool_call_id": call_id, "name": name}

async def run_scenario(scenario: Dict[str, Any]):
    logger.info(f"Running Scenario: {scenario['name']}")
    
    llm = MockLLMAdapter([scenario])
    mcp = AsyncMock()
    mcp.execute_tool.return_value = "Success"
    
    registry = MagicMock()
    registry.to_openai_format.return_value = []
    registry.get_tool.return_value = MagicMock(input_schema={})
    registry.resolve_tool_call.side_effect = lambda name: ("local-mcp", name)
    
    loop = AgentLoop(max_turns=scenario.get("max_turns", 5))
    
    response, state = await loop.run(
        user_message=scenario["input"],
        llm_adapter=llm,
        mcp_orchestrator=mcp,
        tool_registry=registry
    )
    
    logger.info(f"Outcome: {state.status}, Turns: {state.turn}")
    return state

async def main():
    scenarios = [
        {
            "name": "Simple Request",
            "input": "List files",
            "responses": [
                {
                    "tool_calls": [{"name": "list_directory", "input": {"path": "."}}],
                    "content": "I will list the files."
                },
                {
                    "content": "Files are: file1.txt, file2.txt"
                }
            ]
        },
        {
            "name": "Planning Interruption",
            "input": "Implement complex feature",
            "responses": [
                {
                    "tool_calls": [{"name": "propose_plan", "input": {"goal": "Complex Feature", "steps": ["Step 1", "Step 2"]}}],
                    "content": "I need to plan first."
                }
            ]
        },
        {
            "name": "Max Turns Enforcement",
            "input": "Infinite loop",
            "max_turns": 2,
            "responses": [
                {
                    "tool_calls": [{"name": "nop", "input": {}}],
                    "content": "Looping..."
                },
                {
                    "tool_calls": [{"name": "nop", "input": {}}],
                    "content": "Still looping..."
                },
                {
                    "tool_calls": [{"name": "nop", "input": {}}],
                }
            ]
        },
        {
            "name": "Large Scale Edit",
            "input": "Refactor multiple files",
            "responses": [
                {
                    "tool_calls": [
                        {"name": "read_file", "input": {"path": "file1.py"}},
                        {"name": "read_file", "input": {"path": "file2.py"}},
                        {"name": "edit_diff", "input": {"path": "file1.py", "diff": "..."}}
                    ],
                    "content": "Reading and editing."
                },
                {
                    "content": "Refactoring complete."
                }
            ]
        }
    ]

    total_passed = 0
    for s in scenarios:
        state = await run_scenario(s)
        
        # Verification
        if s["name"] == "Planning Interruption":
            if state.turns_history[-1].outcome == TurnOutcome.PLANNING:
                logger.info("PASS: Planning interruption detected.")
                total_passed += 1
            else:
                logger.error(f"FAIL: Expected PLANNING outcome, got {state.turns_history[-1].outcome}")
        elif s["name"] == "Max Turns Enforcement":
            if state.status == "completed" and state.turn >= 2:
                logger.info("PASS: Max turns enforced.")
                total_passed += 1
            else:
                logger.error(f"FAIL: Expected turn limit reached, status: {state.status}, turns: {state.turn}")
        elif s["name"] == "Large Scale Edit":
            if state.total_tool_calls == 3:
                logger.info("PASS: Multiple tool calls per turn executed.")
                total_passed += 1
            else:
                logger.error(f"FAIL: Expected 3 tool calls, got {state.total_tool_calls}")
        else:
            if state.status == "completed":
                logger.info("PASS: Standard scenario completed.")
                total_passed += 1
            else:
                logger.error(f"FAIL: Scenario failed with status {state.status}")

    print(f"\nFinal Result: {total_passed}/{len(scenarios)} passed.")

if __name__ == "__main__":
    asyncio.run(main())
