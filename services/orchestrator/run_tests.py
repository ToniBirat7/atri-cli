#!/usr/bin/env python3
"""
Run integration tests and capture output
"""
import subprocess
import sys

def run_tests():
    """Run pytest tests"""
    print("=" * 80)
    print("PHASE 1 VALIDATION: Running Integration Tests")
    print("=" * 80)
    print()
    
    # Run integration tests
    print("Running integration tests (test_integration.py)...")
    print("-" * 80)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_integration.py", "-v", "--tb=short"],
        capture_output=False,
        text=True
    )
    
    print()
    print("-" * 80)
    if result.returncode == 0:
        print("Integration tests PASSED")
    else:
        print("Integration tests FAILED")
    
    print()
    print("=" * 80)
    print("Running LLM adapter tests (test_llm_adapter.py)...")
    print("-" * 80)
    result2 = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_llm_adapter.py", "-v", "--tb=short"],
        capture_output=False,
        text=True
    )
    
    print()
    print("-" * 80)
    if result2.returncode == 0:
        print("LLM adapter tests PASSED")
    else:
        print("LLM adapter tests FAILED")
    
    print()
    print("=" * 80)
    print("Running MCP orchestrator tests (test_mcp_orchestrator.py)...")
    print("-" * 80)
    result3 = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_mcp_orchestrator.py", "-v", "--tb=short"],
        capture_output=False,
        text=True
    )
    
    print()
    print("-" * 80)
    if result3.returncode == 0:
        print("MCP orchestrator tests PASSED")
    else:
        print("MCP orchestrator tests FAILED")
    
    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    all_passed = result.returncode == 0 and result2.returncode == 0 and result3.returncode == 0
    if all_passed:
        print("All test suites PASSED!")
    else:
        print("Some tests FAILED - check output above")
    print("=" * 80)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(run_tests())
