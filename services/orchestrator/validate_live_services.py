#!/usr/bin/env python3
"""
Phase 1 Validation Report - Comprehensive Testing
Tests live services and GPU utilization
"""
import subprocess
import sys
import os
import json
import time
import asyncio
import httpx

async def test_health_check():
    """Test service health endpoints"""
    print("\n" + "="*80)
    print("TEST 1: Service Health Checks")
    print("="*80)
    
    services = {
        "llama.cpp": "http://127.0.0.1:8000/health",
        "Orchestrator": "http://127.0.0.1:8001/health",
        "Frontend": "http://127.0.0.1:3000/",
    }
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services.items():
            try:
                resp = await client.get(url)
                status = "ok" if resp.status_code < 400 else "error"
                print(f"  {status} {name:15} {url:40} [{resp.status_code}]")
            except Exception as e:
                print(f"  error {name:15} {str(e)[:50]}")

async def test_tool_listing():
    """Test getting available tools"""
    print("\n" + "="*80)
    print("TEST 2: Tool Registry")
    print("="*80)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("http://127.0.0.1:8001/tools")
            if resp.status_code == 200:
                tools = resp.json()
                print(f"  ok Retrieved {len(tools.get('tools', []))} tools")
                for tool in tools.get('tools', [])[:3]:
                    print(f"    - {tool.get('function', {}).get('name', 'unknown')}")
            else:
                print(f"  error Failed to get tools [{resp.status_code}]")
    except Exception as e:
        print(f"  error Error: {e}")

async def test_simple_chat():
    """Test simple chat without tools"""
    print("\n" + "="*80)
    print("TEST 3: Simple Chat (No Tools)")
    print("="*80)
    
    payload = {
        "message": "Hello! What's your name?",
        "system": "You are a helpful assistant."
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            start = time.time()
            resp = await client.post(
                "http://127.0.0.1:8001/chat",
                json=payload
            )
            elapsed = time.time() - start
            
            if resp.status_code == 200:
                data = resp.json()
                response = data.get('response', '')
                print(f"  ok Chat completed in {elapsed:.2f}s")
                print(f"  Response: {response[:100]}{'...' if len(response) > 100 else ''}")
                print(f"  Turns: {data.get('turns', 0)}")
            else:
                print(f"  error Chat failed [{resp.status_code}]")
                print(f"    {resp.text[:200]}")
    except Exception as e:
        print(f"  error Error: {e}")

async def test_tool_calling():
    """Test chat with tool calling"""
    print("\n" + "="*80)
    print("TEST 4: Chat with Tool Calling")
    print("="*80)
    
    # Exercise tool calling WITHIN the MCP sandbox. The repo root is the
    # orchestrator service's grandparent dir; /tmp would be out of bounds and
    # always permission-denied, which never validated tool calling.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    payload = {
        "message": "How many Python files are in the services/mcp directory? Use list_directory.",
        "allowed_directory": repo_root,
        "permission_mode": "bypassPermissions",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            start = time.time()
            resp = await client.post(
                "http://127.0.0.1:8001/chat",
                json=payload
            )
            elapsed = time.time() - start
            
            if resp.status_code == 200:
                data = resp.json()
                response = data.get('response', '')
                # ChatResponse exposes the count as 'tool_calls', not 'tools_used'.
                tools_used = data.get('tool_calls', data.get('tools_used', 0))
                print(f"  ok Chat completed in {elapsed:.2f}s")
                print(f"  Response: {response[:100]}{'...' if len(response) > 100 else ''}")
                print(f"  Tools used: {tools_used}")
            else:
                print(f"  error Chat failed [{resp.status_code}]")
                print(f"    {resp.text[:200]}")
    except Exception as e:
        print(f"  error Error: {e}")

async def test_gpu_status():
    """Check GPU utilization"""
    print("\n" + "="*80)
    print("TEST 5: GPU Utilization Status")
    print("="*80)
    
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu',
             '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            info = result.stdout.strip()
            print(f"  ok GPU Status:")
            print(f"    {info}")
        else:
            print(f"  warning nvidia-smi not available")
    except Exception as e:
        print(f"  warning GPU check skipped: {e}")

async def main():
    """Run all validation tests"""
    print("\n" + "="*90)
    print(" "*20 + "PHASE 1 VALIDATION: LIVE SERVICE TESTING")
    print("="*90)
    
    # Check if services are running
    print("\nChecking service availability...")
    
    # Run tests
    await test_health_check()
    await test_tool_listing()
    await test_simple_chat()
    await test_tool_calling()
    await test_gpu_status()
    
    print("\n" + "="*90)
    print(" "*25 + "VALIDATION COMPLETE")
    print("="*90)
    print("\nNext Steps:")
    print("  1. Review test results above")
    print("  2. Check GPU utilization numbers")
    print("  3. Test via frontend browser at http://127.0.0.1:3000")
    print("  4. Run: make dev-logs to see detailed logs")
    print("\n")

if __name__ == "__main__":
    asyncio.run(main())
