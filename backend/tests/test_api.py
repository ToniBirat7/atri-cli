import requests
import pytest

def test_root_endpoint_returns_200_and_contains_nebula():
    """
    Tests if the root endpoint returns a 200 status code and contains 'Nebula'.
    """
    # NOTE: Replace 'http://localhost:8080/' with the actual root endpoint URL for your backend
    url = "http://localhost:8080/" 
    
    response = requests.get(url)
    
    assert response.status_code == 200, f"Root endpoint returned status code {response.status_code}"
    assert "Nebula" in response.text, "Root endpoint response does not contain 'Nebula'"