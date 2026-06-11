import pytest
from fastapi.testclient import TestClient
from api import app
import io

client = TestClient(app)

def test_health():
    """API is running"""
    response = client.get("/docs")
    assert response.status_code == 200

def test_get_obligations_existing_document():
    """Get obligations for existing document"""
    response = client.get("/obligations/sample_contract")
    assert response.status_code == 200
    data = response.json()
    assert "obligations" in data
    assert len(data["obligations"]) > 0

def test_get_risks_existing_document():
    """Get risks for existing document"""
    response = client.get("/risks/sample_contract")
    assert response.status_code == 200
    data = response.json()
    assert "risks" in data
    assert len(data["risks"]) > 0

def test_get_graph_existing_document():
    """Get graph data for existing document"""
    response = client.get("/graph/sample_contract")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) > 0

def test_get_obligations_nonexistent_document():
    """Get obligations for document that doesn't exist"""
    response = client.get("/obligations/nonexistent_doc")
    assert response.status_code == 200
    data = response.json()
    assert data["obligations"] == []

def test_get_risks_nonexistent_document():
    """Get risks for document that doesn't exist"""
    response = client.get("/risks/nonexistent_doc")
    assert response.status_code == 200
    data = response.json()
    assert data["risks"] == []

def test_analyze_invalid_file():
    """Upload non-PDF file should handle gracefully"""
    fake_file = io.BytesIO(b"not a pdf content")
    response = client.post(
        "/analyze",
        files={"file": ("test.pdf", fake_file, "application/pdf")}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "error"