# Agent Loop

**File:** `services/orchestrator/agent_loop.py`

## Purpose

The AgentLoop is the core reasoning engine. It runs the **ReAct** (Reason + Act) pattern: the LLM reasons about what to do, selects tools, executes them, observes results, and repeats until a final answer is ready or a budget limit is hit.

## TurnOutcome enum

```python
class TurnOutcome(str, Enum):
    TOOL_CALLS        # LLM called ≥1 tool; loop continues
    NO_TOOL_CALLS     # LLM returned a plain response; loop terminates (answer ready)
    PLANNING          # (reserved) planning phase turn
    VERIFICATION      # (reserved) verification phase turn
    MAX_TURNS_REACHED # budget exhausted; return whatever the last response was
    ERROR             # unrecoverable error; propagate to caller
    REVIEW            # (reserved) review phase
```

The loop continues as long as `TurnOutcome == TOOL_CALLS`. It terminates on `NO_TOOL_CALLS` (model done), `MAX_TURNS_REACHED`, or `ERROR`.

## Budget controls

| Control | Config key | Default |
|---------|-----------|---------|
| Max turns | `AGENT_MAX_TURNS` | 10 |
| Max tool calls per turn | `AGENT_MAX_TOOL_CALLS_PER_TURN` | 3 |
| LLM request timeout | `LLM_TIMEOUT_SECONDS` | 120s (patched to 300s for 26B) |
| Tool execution timeout | `MCP_TOOL_TIMEOUT_SECONDS` | 10s |

## Data structures

```python
@dataclass
class Turn:
    turn_number: int
    user_input: Optional[str]
    llm_response: Optional[str]
    tool_calls_requested: int
    tool_calls_executed: int
    tool_calls: List[str]       # tool names called this turn
    outcome: Optional[TurnOutcome]
    error: Optional[str]
    metadata: Dict[str, Any]

@dataclass
class AgentState:
    turn: int
    messages: List[Dict[str, str]]   # OpenAI-format message history
    turns_history: List[Turn]
    total_tool_calls: int
    final_response: Optional[str]
    status: str                      # "initialized" → "running" → "done"/"error"
```

## Loop phases (planned)

The docstring lists 7 phases of progressive complexity:
- Phase 1: Basic deterministic loop with budgets ✓
- Phase 2: Streaming responses ✓
- Phase 3: Error recovery and backtracking ✓
- Phase 5: Circuit-breaker, retry logic, observability ✓
- Phase 7: Full observability with structured logging and tracing ✓

## Tool validation

Tool call arguments are validated against the MCP tool schema **before** execution (line ~219). If the model passes unexpected field names, a `ValueError` is raised immediately.

**Known gotcha:** `get_file_info` expects field `target_path`, not `path`. The model sometimes uses `path` — this raises `ValueError: Unexpected fields for tool 'get_file_info': path`. This is a model hallucination of the field name; the tool schema is authoritative.

## Observability

Every turn emits a structured JSON log line via `_log_event()`:
```json
{"event": "turn_start", "request_id": "...", "turn_id": "...", "turn_number": 2}
```

## Related pages

- [[architecture]] — where the loop fits in the system
- [[mcp-tools]] — tools the loop can call
- [[orchestrator]] — how the API layer invokes the loop
- [[known-issues]] — timeout and schema bugs
