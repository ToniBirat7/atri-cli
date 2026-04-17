.PHONY: help dev-up dev-down logs clean install test build

# Model runtime toggle
ENABLE_THINKING ?= false
LLAMA_CHAT_TEMPLATE_KWARGS := {"enable_thinking":$(ENABLE_THINKING)}

# llama.cpp runtime/build knobs
LLAMA_THREADS ?= 12
LLAMA_N_GPU_LAYERS ?= 999
LLAMA_CTX_SIZE ?= 16384
LLAMA_CUDA_ARCH ?= 86

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# Service ports
LLAMA_PORT := 8000
ORCHESTRATOR_PORT := 8001
FRONTEND_PORT := 3000

help: ## Show this help message
	@echo "$(BLUE)Tarbar_AI Development Makefile$(NC)"
	@echo ""
	@echo "$(YELLOW)Local Development:$(NC)"
	@echo "  make dev-up              Start all services (llama, orchestrator, frontend)"
	@echo "  make dev-down            Stop all services"
	@echo "  make logs                View logs from all services"
	@echo ""
	@echo "$(YELLOW)Individual Services:$(NC)"
	@echo "  make llama               Start llama.cpp server"
	@echo "  make llama-build-gpu     Rebuild llama.cpp with CUDA support"
	@echo "  make mcp                 Start MCP server (STDIO)"
	@echo "  make orchestrator        Start orchestrator API"
	@echo "  make frontend            Start frontend dev server"
	@echo ""
	@echo "$(YELLOW)Development:$(NC)"
	@echo "  make install             Install all dependencies"
	@echo "  make test                Run tests"
	@echo "  make build               Build for production"
	@echo ""
	@echo "$(YELLOW)Utilities:$(NC)"
	@echo "  make clean               Remove build artifacts and .env files"
	@echo "  make health              Check service health"
	@echo "  make env                 Create .env files with defaults"

# ===== Development Workflow =====

dev-up: env ## Start all services (llama + orchestrator + frontend)
	@echo "$(GREEN)Starting Tarbar_AI services...$(NC)"
	@echo "$(BLUE)1. Starting llama.cpp on port $(LLAMA_PORT)$(NC)"
	@(cd runtime/llm/llama.cpp && ./build/bin/llama-server -m ../../../models/gemma-4-e2b-it-Q4_K_M.gguf --jinja --chat-template-kwargs '$(LLAMA_CHAT_TEMPLATE_KWARGS)' --port $(LLAMA_PORT) --threads $(LLAMA_THREADS) --n-gpu-layers $(LLAMA_N_GPU_LAYERS) --ctx-size $(LLAMA_CTX_SIZE) --api-key secret > ../../../llama.log 2>&1 &)
	@sleep 3
	@echo "$(BLUE)2. Starting orchestrator on port $(ORCHESTRATOR_PORT)$(NC)"
	@(cd services/orchestrator && \
		if [ ! -x .venv/bin/python ]; then \
			echo "$(RED)Missing services/orchestrator/.venv. Run 'make install' first.$(NC)"; \
			exit 1; \
		fi && \
		.venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port $(ORCHESTRATOR_PORT) > ../../orchestrator.log 2>&1 &)
	@sleep 2
	@echo "$(BLUE)3. Starting frontend on port $(FRONTEND_PORT)$(NC)"
	@(cd apps/frontend && npm run dev > ../../frontend.log 2>&1 &)
	@sleep 3
	@echo "$(GREEN)✓ All services started!$(NC)"
	@echo ""
	@echo "$(YELLOW)Service URLs:$(NC)"
	@echo "  llama.cpp:      http://127.0.0.1:$(LLAMA_PORT)"
	@echo "  Orchestrator:   http://127.0.0.1:$(ORCHESTRATOR_PORT)"
	@echo "  Frontend:       http://127.0.0.1:$(FRONTEND_PORT)"
	@echo ""
	@echo "Current llama.cpp settings: threads=$(LLAMA_THREADS), n-gpu-layers=$(LLAMA_N_GPU_LAYERS), ctx=$(LLAMA_CTX_SIZE), cuda-arch=$(LLAMA_CUDA_ARCH)"
	@echo ""
	@echo "$(YELLOW)Logs:$(NC)"
	@echo "  make logs                View all logs"

dev-down: ## Stop all services
	@echo "$(YELLOW)Stopping services...$(NC)"
	@lsof -ti tcp:$(LLAMA_PORT) | xargs -r kill || true
	@lsof -ti tcp:$(ORCHESTRATOR_PORT) | xargs -r kill || true
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs -r kill || true
	@sleep 1
	@echo "$(GREEN)✓ Services stopped$(NC)"

logs: ## Tail logs from all services
	@echo "$(BLUE)Tailing service logs (Ctrl+C to exit)...$(NC)"
	@echo ""
	@tail -f llama.log orchestrator.log frontend.log 2>/dev/null || echo "$(RED)Log files not found. Run 'make dev-up' first.$(NC)"

# ===== Individual Services =====

llama: env ## Start llama.cpp server only
	@echo "$(GREEN)Starting llama.cpp...$(NC)"
	@if [ ! -f "runtime/llm/llama.cpp/build/bin/llama-server" ]; then \
		echo "$(RED)Error: llama-server not found. Build llama.cpp first.$(NC)"; \
		exit 1; \
	fi
	@if [ ! -f "models/gemma-4-e2b-it-Q4_K_M.gguf" ]; then \
		echo "$(RED)Error: Model not found at models/gemma-4-e2b-it-Q4_K_M.gguf$(NC)"; \
		exit 1; \
	fi
	@cd runtime/llm/llama.cpp && ./build/bin/llama-server -m ../../../models/gemma-4-e2b-it-Q4_K_M.gguf --jinja --chat-template-kwargs '$(LLAMA_CHAT_TEMPLATE_KWARGS)' --port $(LLAMA_PORT) --threads $(LLAMA_THREADS) --n-gpu-layers $(LLAMA_N_GPU_LAYERS) --ctx-size $(LLAMA_CTX_SIZE) --api-key secret
orchestrator: ## Start orchestrator API only (requires llama.cpp running)
	@echo "$(GREEN)Starting orchestrator...$(NC)"
	@cd services/orchestrator && \
		if [ ! -x .venv/bin/python ]; then \
			echo "$(RED)Missing services/orchestrator/.venv. Run 'make install' first.$(NC)"; \
			exit 1; \
		fi && \
		.venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port $(ORCHESTRATOR_PORT) --reload

mcp: ## Start MCP server (STDIO) for testing
	@echo "$(GREEN)Starting MCP server...$(NC)"
	@cd services/mcp && fastmcp run main.py:mcp

frontend: ## Start frontend dev server
	@echo "$(GREEN)Starting frontend...$(NC)"
	@cd apps/frontend && npm run dev

# ===== Dependencies & Setup =====

install: ## Install all dependencies
	@echo "$(BLUE)Installing dependencies...$(NC)"
	@echo "$(YELLOW)1. Installing frontend dependencies...$(NC)"
	@cd apps/frontend && npm install
	@echo "$(YELLOW)2. Installing orchestrator dependencies...$(NC)"
	@cd services/orchestrator && \
		python -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --upgrade pip && \
		python -m pip install -r requirements.txt
	@echo "$(YELLOW)3. Installing MCP service dependencies...$(NC)"
	@cd services/mcp && pip install -r requirements.txt 2>/dev/null || echo "$(YELLOW)   (No requirements.txt, FastMCP assumed installed)$(NC)"
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

env: ## Create .env files with defaults
	@if [ ! -f "services/orchestrator/.env" ]; then \
		echo "$(YELLOW)Creating services/orchestrator/.env$(NC)"; \
		cp services/orchestrator/.env.example services/orchestrator/.env 2>/dev/null || \
		printf '%s\n' \
			"LLM_BASE_URL=http://127.0.0.1:$(LLAMA_PORT)/v1" \
			"LLM_API_KEY=secret" \
			"LLM_MODEL=local-model" \
			"LLM_TEMPERATURE=1.0" \
			"LLM_TOP_P=0.95" \
			"LLM_TOP_K=64" \
			"LLM_MAX_TOKENS=2048" \
			"LLM_TIMEOUT_SECONDS=30" \
			"LLM_PARALLEL_TOOL_CALLS=true" \
			"" \
			"MCP_DEFAULT_TRANSPORT=stdio" \
			"MCP_TOOL_TIMEOUT_SECONDS=10" \
			"MCP_MAX_TOOL_CALL_RETRIES=2" \
			"" \
			"AGENT_MAX_TURNS=10" \
			"AGENT_MAX_TOOL_CALLS_PER_TURN=3" \
			"AGENT_ENABLE_TOOL_USE=true" \
			"AGENT_ENABLE_THINKING=$(ENABLE_THINKING)" \
			"AGENT_STREAM_RESPONSES=false" \
			"" \
			"LOG_LEVEL=INFO" \
			"ENABLE_OBSERVABILITY=true" > services/orchestrator/.env; \
	fi
	@echo "$(GREEN)✓ .env files ready$(NC)"

# ===== Testing & Health Checks =====

health: ## Check service health
	@echo "$(BLUE)Checking service health...$(NC)"
	@echo ""
	@echo "$(YELLOW)LLM (llama.cpp)$(NC)"
	@curl -s http://127.0.0.1:$(LLAMA_PORT)/v1/models -H "Authorization: Bearer secret" | jq '.data[0].id // "No models"' || echo "  $(RED)✗ Not running$(NC)"
	@echo ""
	@echo "$(YELLOW)Orchestrator$(NC)"
	@curl -s http://127.0.0.1:$(ORCHESTRATOR_PORT)/health | jq '.status' || echo "  $(RED)✗ Not running$(NC)"
	@echo ""
	@echo "$(YELLOW)Frontend$(NC)"
	@curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$(FRONTEND_PORT) && echo "  $(GREEN)✓ Running$(NC)" || echo "  $(RED)✗ Not running$(NC)"

test: ## Run test suite (Phase 3+)
	@echo "$(BLUE)Running tests...$(NC)"
	@echo "$(YELLOW)Unit tests for orchestrator$(NC)"
	@cd services/orchestrator && \
		if [ ! -x .venv/bin/python ]; then \
			echo "$(RED)Missing services/orchestrator/.venv. Run 'make install' first.$(NC)"; \
			exit 1; \
		fi && \
		.venv/bin/python -m pytest tests/ -v || echo "$(YELLOW)No tests found yet (Phase 3+)$(NC)"

# ===== Build & Deploy =====

build: ## Build for production (Phase 9+)
	@echo "$(BLUE)Building for production...$(NC)"
	@echo "$(YELLOW)1. Building frontend...$(NC)"
	@cd apps/frontend && npm run build
	@echo "$(YELLOW)2. Preparing orchestrator...$(NC)"
	@cd services/orchestrator && \
		if [ ! -x .venv/bin/python ]; then \
			echo "$(RED)Missing services/orchestrator/.venv. Run 'make install' first.$(NC)"; \
			exit 1; \
		fi && \
		.venv/bin/python -m pip install -r requirements.txt --upgrade
	@echo "$(GREEN)✓ Build complete$(NC)"

# ===== Cleanup =====

clean: dev-down ## Clean build artifacts and temporary files
	@echo "$(YELLOW)Cleaning artifacts...$(NC)"
	@rm -f llama.log orchestrator.log frontend.log
	@rm -f services/orchestrator/.env
	@rm -rf apps/frontend/.next
	@rm -rf apps/frontend/node_modules
	@rm -rf services/orchestrator/__pycache__ services/orchestrator/.pytest_cache
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

llama-build-gpu: ## Rebuild llama.cpp with CUDA support for NVIDIA GPUs
	@echo "$(BLUE)Configuring llama.cpp with CUDA backend...$(NC)"
	@cd runtime/llm/llama.cpp && \
		cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DGGML_NATIVE=ON -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=$(LLAMA_CUDA_ARCH) && \
		cmake --build build --config Release -j $$(nproc) --target llama-server llama-cli

# ===== Internal Targets =====

.PHONY: _check_model
_check_model:
	@if [ ! -f "models/gemma-4-e2b-it-Q4_K_M.gguf" ]; then \
		echo "$(RED)Error: Model file not found$(NC)"; \
		echo "Expected: models/gemma-4-e2b-it-Q4_K_M.gguf"; \
		echo ""; \
		echo "Download from: https://huggingface.co/lmstudio-ai/gemma-4-e2b-it-GGUF"; \
		exit 1; \
	fi
