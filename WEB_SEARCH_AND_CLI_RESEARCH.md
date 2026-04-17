# Web Search and CLI Expansion Research for Tarbar_AI

## Scope

This note answers two related questions:

1. How can Tarbar_AI add web search so the model can use up-to-date information at request time?
2. How can Tarbar_AI offer both a browser UI and a CLI UI, sharing the same backend, in a Claude Code-like workflow?

Assumption: the current model is a text decoder only. It is not multimodal and it does not inherently know live web facts. That means any real-time information must come from external tools and retrieval, not from the model weights themselves.

## What the repo already has

Tarbar_AI already has the main ingredients needed for a search-enabled agent system:

- A deterministic orchestrator and agent loop in [services/orchestrator/agent_loop.py](services/orchestrator/agent_loop.py)
- Tool registration and namespaced tool routing in [services/orchestrator/tool_registry.py](services/orchestrator/tool_registry.py)
- MCP-based tool execution in [services/orchestrator/mcp_orchestrator.py](services/orchestrator/mcp_orchestrator.py)
- Prompt-policy selection in [services/orchestrator/prompt_policy.py](services/orchestrator/prompt_policy.py)
- A browser frontend in [apps/frontend/src/app/page.tsx](apps/frontend/src/app/page.tsx)
- A backend-for-frontend request flow in [apps/frontend/src/app/api/chat/route.ts](apps/frontend/src/app/api/chat/route.ts)
- Persistent conversations and audit trails in [services/orchestrator/database.py](services/orchestrator/database.py)
- Streaming support through the orchestrator API in [services/orchestrator/api.py](services/orchestrator/api.py)
- A live filesystem MCP server in [services/mcp/main.py](services/mcp/main.py)

That means Tarbar_AI is already structured correctly for adding web search as just another tool layer.

## Core conclusion

Web search should not be treated as a property of the model.
It should be treated as a tool capability managed by the orchestrator.

The model can decide when to use a search tool if it supports tool calling, but the actual search, page fetch, filtering, citation building, and safety checks should live outside the model.

For a text-only decoder model, that is the right architecture.

## How web search should work

The cleanest architecture is a three-step retrieval flow:

1. Query planning
   - The model turns the user request into one or more search queries.
   - The orchestrator can also rewrite or refine the query if needed.

2. Search and fetch
   - A dedicated search tool queries a search provider or local search index.
   - A follow-up fetch tool retrieves page content for the top results.

3. Grounded answer generation
   - The orchestrator passes the top snippets or extracted content back to the model.
   - The model answers using only the retrieved evidence and cites the sources.

This is closer to retrieval-augmented generation than to “making the model know the internet.”

## Does llama.cpp support this?

Yes, but with an important distinction.

According to llama.cpp function-calling documentation, tool calling is supported through native and generic handlers, and some model families have built-in tool names such as `web_search` or `brave_search`. The docs also note that generic tool calling works when a model/template is not recognized natively, although it can be less efficient.

That means:

- If the model/template supports tool calling reliably, it can trigger a search tool.
- If it does not support native search tools, the orchestrator can still expose a generic `search_web` or `research_web` tool.
- If the model is weak at tool calling, the orchestrator can still recover by forcing a search action when the user intent is clearly time-sensitive or web-dependent.

For Tarbar_AI specifically, the current model being text-only is not a blocker for search, but it does mean the search layer must be external and tool-driven.

## Important limitation: text decoder only

Because the model is not multimodal:

- It cannot inspect screenshots, images, PDFs, or browser DOMs directly unless you add tools that convert those inputs into text.
- It cannot “browse” by itself.
- It cannot guarantee freshness unless the orchestrator gives it live search results.

So the right mental model is:

- model = reasoning and response synthesis
- search tool = real-time web access
- fetch/crawl tool = page extraction
- orchestrator = policy, routing, safety, caching, citations

## Search backend options

There are several viable search backends. Each has different tradeoffs.

### 1. Brave Search API

Brave’s documentation positions the API as a real-time web search product with fresh results, snippets, news, and AI-optimized context. It also highlights grounding/citations, streaming, and an OpenAI SDK-compatible answers mode.

Why it fits Tarbar_AI:

- Fresh results with a simple API
- Good for production-style grounding
- Can be wrapped as an MCP tool or called directly from the orchestrator
- Includes result metadata and snippets that help citation generation

Tradeoffs:

- Paid API usage
- External dependency and rate limits
- Search quality depends on query quality and result ranking
- Still needs a fetch step for deep page reading

### 2. Tavily

Tavily markets itself as an LLM-friendly web search and retrieval platform. The docs emphasize search, webpage extraction, crawling, and research workflows.

Why it fits Tarbar_AI:

- Designed for LLM apps
- Easy search + extract path
- Good if you want a research-oriented API with structured outputs

Tradeoffs:

- External dependency and usage cost
- You still need prompt-injection defenses for page text
- May be overkill if you only need lightweight search

### 3. Self-hosted search stack

Examples:

- SearXNG as a metasearch layer
- Custom web crawler and page fetcher
- A local index for project docs plus public web search for external facts

Why it fits Tarbar_AI:

- More control
- Better privacy
- No vendor lock-in
- Good for local-first positioning

Tradeoffs:

- More engineering work
- Higher maintenance burden
- Crawling and ranking quality are your responsibility
- Needs stronger anti-abuse and content filtering

## Best design for Tarbar_AI

For this project, the best path is likely a hybrid:

- Start with one external search provider for public web search
- Add a page fetch/extract tool for reading the best results
- Keep a local/project-document retrieval path separate from public web search
- Expose both through MCP so the orchestrator treats them uniformly

That gives you:

- real-time public facts
- local repo knowledge
- a single tool-routing system
- a clean path for CLI and web clients to share behavior

## Recommended tool set

I would add these tools in phases:

- `search_web`
  - Accepts a query string, optional recency, language, and domain filters
  - Returns ranked result metadata, snippets, and source URLs

- `fetch_url`
  - Fetches and extracts text from a specific URL
  - Returns title, canonical URL, extracted text, and content type

- `search_project_docs`
  - Searches local docs, markdown, notebooks, or code comments
  - Good for repo-aware answers

- `summarize_sources`
  - Turns fetched content into concise evidence blocks with citations

- `cite_answer`
  - Produces a response with quoted or paraphrased evidence and source links

## Key architectural challenge: search is not the same as answer generation

A web search stack can fail in several ways if you blur these layers:

- The search engine may return irrelevant results.
- The page fetch may fail or get blocked.
- The model may over-trust a single source.
- The model may hallucinate facts that were not in the fetched pages.

To avoid that, keep the orchestration split:

- Search tool finds candidates
- Fetch tool extracts evidence
- Model writes the answer
- Orchestrator enforces citations and truncation

## Security and reliability challenges

Web search introduces new risks that do not exist in the local filesystem tools.

### 1. Prompt injection from web pages

Web pages can contain malicious or misleading instructions like “ignore previous instructions.”

Mitigations:

- Strip or classify instruction-like text before sending to the model
- Mark fetched content as untrusted data
- Keep search/fetch outputs in a separate tool-result channel
- Never allow web text to overwrite system policy

### 2. Copyright and content policy

You should avoid copying large amounts of source text into the answer.

Mitigations:

- Return short excerpts and summaries
- Prefer citations and paraphrases
- Cache metadata, not huge page bodies
- Set result-size caps

### 3. Freshness versus correctness

Search results are current, but not always correct.

Mitigations:

- Use multiple sources for important factual claims
- Prefer authoritative sources when possible
- Add recency filters when the user asks for current info
- Let the model say when evidence is weak or conflicting

### 4. Cost and latency

A search plus fetch flow is slower than a pure model response.

Mitigations:

- Cache search results briefly
- Cache fetched page text by URL hash
- Limit the number of pages fetched per request
- Add a fast path for queries that do not need web data

### 5. Rate limits and provider dependency

Public search APIs can throttle or fail.

Mitigations:

- Add retries with backoff
- Add a provider abstraction so you can swap Brave, Tavily, or SearXNG
- Fall back to another search backend if the primary one is unavailable

## Can the current model support web search?

Short answer: yes, but only through tools.

What it can do:

- Choose to call a search tool if tool calling is supported
- Use fetched snippets and page text to answer questions
- Produce grounded answers with citations

What it cannot do on its own:

- Access the internet without tools
- Know current events from the weights alone
- Perform multimodal browsing
- Guarantee that a result is fresh unless the backend fetches it live

So the model is compatible with web search as long as the backend supplies the search tools and the orchestration loop is strong enough to use them.

## CLI plus web, same backend

This is very doable and is a strong design choice.

The right pattern is:

- Keep the orchestrator as the single backend control plane
- Build the browser UI as one thin client
- Build the CLI as another thin client
- Let both clients talk to the same HTTP/SSE endpoints

That means the backend owns:

- auth
- prompt policy
- tool routing
- conversation persistence
- search integration
- citations
- observability

And the clients only own presentation.

## What the CLI should look like

A Claude Code-like CLI should behave like a terminal-native agent workspace.

Likely features:

- interactive prompt loop
- streaming assistant output
- visible tool events
- slash commands such as:
  - `/search`
  - `/resume`
  - `/clear`
  - `/tools`
  - `/model`
  - `/profile`
- support for local workspace root selection
- support for continuing a conversation from a saved session ID
- optional non-interactive mode for scripting and CI

## CLI implementation options

### Option A: Python CLI

Best fit for this repo because the backend is already Python.

Likely stack:

- Typer or Click for command parsing
- Rich for terminal UI and colored streaming output
- prompt_toolkit for interactive input and multiline editing
- SSE or WebSocket client to receive streamed events

Pros:

- Same language as orchestrator
- Easier shared data models
- Simple packaging and deployment

### Option B: Node.js CLI

Useful if you want a tighter pairing with the Next.js frontend ecosystem.

Pros:

- Good terminal UX libraries
- Easy to reuse TypeScript types from the frontend side

Cons:

- Adds a second language/runtime to the repo
- Less natural fit for the Python backend

For Tarbar_AI, Python is the cleaner first choice.

## How CLI and web should share the same backend

The backend should expose one common conversation protocol that both clients can use.

A practical split would be:

- `POST /chat` for simple request/response
- `POST /chat/stream` for SSE streaming
- `GET /conversations` and `GET /conversations/{id}` for history
- `GET /tools` for discovery
- `POST /validate-directory` or similar for workspace scoping
- search tool endpoints hidden behind the orchestrator and MCP

Both clients should send the same request metadata:

- message text
- conversation ID
- prompt profile
- allowed directory or workspace root
- auth token
- optional model/profile overrides

## Why this is better than separate backends

A single backend means:

- one policy source of truth
- one tool registry
- one persistence model
- one audit trail
- one set of search safety rules
- one set of evals and benchmarks

That is exactly the right architecture for a web UI plus a terminal UI.

## Recommended backend changes to support both clients

1. Make the orchestrator the sole agent runtime.
2. Add a search provider adapter as either a direct service call or an MCP server.
3. Add a page fetch/extract tool.
4. Keep conversation/session state backend-owned.
5. Expose more metadata in streaming events so the CLI can render tool activity cleanly.
6. Add session resume support so CLI and web can jump into the same conversation.

## Search plus CLI together: the practical end state

The best long-term shape is:

- Web app for visual chat, history, tool inspection, and rich rendering
- CLI for fast terminal workflows, scripting, and power-user usage
- Shared backend for model execution, search, tools, auth, and persistence
- Shared session and prompt-policy logic so the behavior stays identical across surfaces

That gives you the same product idea as Claude Code, but with a browser surface kept in parallel.

## Suggested rollout order

### Phase 1: Search foundation

- Add `search_web`
- Add `fetch_url`
- Add citations and source metadata
- Add prompt policy for web-grounded answers

### Phase 2: CLI client

- Build a terminal client that streams the same backend events
- Support workspace selection and session resume
- Add command shortcuts and slash commands

### Phase 3: Retrieval quality

- Add domain filters, recency filters, and provider fallback
- Add caching
- Add redaction and injection filtering

### Phase 4: Advanced workflows

- Add local docs search
- Add saved research sessions
- Add citations export
- Add batch or scripted CLI mode

## Main risks to watch

- The model may still answer from memory unless the prompt policy forces evidence-based responses for search requests.
- Search results can contain prompt injection, spam, or low-quality sources.
- The CLI can become a separate product if it diverges from the same backend contracts.
- A single provider can become a reliability bottleneck.
- Large fetched pages can blow up token usage quickly.

## Bottom line

Yes, Tarbar_AI can support web search and a CLI mode, but the right architecture is not “teach the model the web.”
It is:

- external search tool
- external fetch tool
- orchestrator-managed grounding
- model used for reasoning and synthesis only
- one shared backend serving both web and CLI clients

That is the cleanest path for a text-only model and the most maintainable path for this repo.

## How Claude Code scales today

Claude Code’s current approach is useful as an implementation model because it avoids hard-coding capability into the model and instead layers scale through tools, session state, and policy files.

### 1. Terminal-first, multi-surface product

Claude Code is not just a CLI. The docs describe the same underlying engine being available in the terminal, VS Code, JetBrains, desktop, web, Slack, and CI/CD. The important design point is that each surface is a thin client over shared backend/session logic.

What to copy:

- one backend conversation runtime
- multiple clients with shared semantics
- same session state and tools across surfaces
- output formatting adapted to the surface, not the model

### 2. Persistent instructions with layered scope

Claude uses multiple instruction layers that are loaded at session start:

- managed organization-wide instructions
- project-level `CLAUDE.md`
- user-level instructions
- local project-only instructions
- topic-specific rule files under `.claude/rules/`

This scales because the model gets concise, scoped guidance without turning every session into a long prompt dump.

What to copy:

- repo-level policy files for Tarbar behavior
- project-scoped defaults for search, CLI, and security
- user-local preferences that do not belong in git
- topic-specific rules for search, CLI, and tool safety

### 3. Memory as a separate system, not a giant prompt

Claude Code distinguishes between human-authored instructions and auto memory. Auto memory stores small, reusable learnings such as build commands, debugging patterns, and project habits in a dedicated memory directory, rather than in ad hoc chat history.

What to copy:

- a dedicated memory layer for recurring project facts
- concise startup memory, with detailed notes split into topic files
- separate project memory from conversation history
- keep memory read-on-demand when possible

### 4. Tools are discovered on demand

Claude Code does not eagerly load every MCP tool into context in the most scalable mode. Tool Search defers tool schemas and discovers them when the task needs them, which keeps context smaller as the tool catalog grows.

This is the key scaling lesson for Tarbar_AI.

What to copy:

- defer tool schemas until relevant
- search tool capabilities instead of preloading everything
- keep only tool names and short descriptions in the startup context
- add threshold-based loading when the context window is small enough

### 5. MCP is the capability plane

Claude Code uses MCP to connect databases, issue trackers, monitoring systems, and custom services. It supports local stdio servers, remote HTTP servers, and remote SSE servers, with HTTP recommended for remote integrations.

The important part is not the transport alone. It is that MCP becomes the uniform way to add capability.

What to copy:

- public capability surface through MCP
- local and remote tools in one registry
- strong auth and scope controls per server
- dynamic refresh when tool lists change
- limits on large tool outputs

### 6. Workflows are explicit and repeatable

Claude Code documents common workflows: codebase exploration, bug fixing, refactoring, tests, PRs, docs, scheduling, and parallel worktrees. That makes it feel scalable because the product teaches the user how to use it for different task shapes.

What to copy:

- task-specific presets or prompt profiles
- docs for common workflows, not just features
- plan mode for safe exploration
- session resume and naming
- parallel worktree/session support for larger work

### 7. CLI ergonomics matter as much as model quality

Claude Code exposes output formats, pipe-in/pipe-out usage, resumable sessions, plan mode, and shell-native commands. This makes it scriptable and usable in automation, not just interactive chat.

What to copy:

- interactive mode plus non-interactive mode
- structured JSON output for automation
- session IDs and resume semantics
- commands like `/resume`, `/tools`, `/memory`, `/mcp`, `/clear`

## What this means for Tarbar_AI

If Tarbar_AI wants to scale, the architecture should separate concerns the same way Claude Code does:

1. Model runtime
  - text-only inference and tool calling

2. Capability plane
  - MCP tools for filesystem, search, docs, databases, and external services

3. Policy plane
  - auth, risk tiers, allowlists, prompt rules, output filtering

4. Session plane
  - resumable conversations, history, memory, worktrees, and audit trail

5. Client plane
  - browser UI, CLI UI, future IDE/Desktop integrations

That separation is what keeps the project from collapsing into a single monolithic chat app.

## Recommended scalable architecture for search plus CLI

The most scalable design is:

- one orchestrator backend
- multiple clients
- search as a pluggable capability
- local docs and public web search as distinct tool categories
- deferred tool discovery rather than preloading every tool into the prompt
- session resume and memory scoped by project or workspace

In practice, that means Tarbar_AI should treat web search the same way Claude Code treats MCP servers:

- connect a provider when needed
- gate it through policy
- keep its scope narrow
- refresh capabilities dynamically
- prevent large or unsafe outputs from overwhelming context

## Scalability risks to design for early

The Claude Code docs suggest several scaling pitfalls worth avoiding in Tarbar:

- giant instruction files reduce adherence
- too many upfront tools bloat context
- untrusted tool outputs can inject bad instructions
- remote transports need reconnection logic
- output from large tools can overwhelm the model context
- CLI and web can drift if they do not share the same backend contract

## Practical takeaway

The Claude Code pattern is not “smarter model first.” It is:

- small, scoped instructions
- persistent memory
- on-demand tool discovery
- a shared backend across surfaces
- explicit workflows and session semantics

That is the model Tarbar_AI should copy if it wants to add live web search and a CLI without turning the system into an unmaintainable prompt pile.

## Related repo files

- [docs/architecture-plan.md](docs/architecture-plan.md)
- [docs/services/orchestrator.md](docs/services/orchestrator.md)
- [docs/services/frontend.md](docs/services/frontend.md)
- [docs/workflows/end-to-end.md](docs/workflows/end-to-end.md)
- [services/orchestrator/api.py](services/orchestrator/api.py)
- [services/orchestrator/agent_loop.py](services/orchestrator/agent_loop.py)
- [services/orchestrator/mcp_orchestrator.py](services/orchestrator/mcp_orchestrator.py)
- [services/mcp/main.py](services/mcp/main.py)
- [apps/frontend/src/app/page.tsx](apps/frontend/src/app/page.tsx)
