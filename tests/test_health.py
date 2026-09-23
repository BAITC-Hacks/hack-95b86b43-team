import asyncio

import httpx

from backend import __version__
from backend.main import create_app


def test_health(tmp_path):
    response = request("/health", tmp_path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def request(path, tmp_path):
    async def run():
        transport = httpx.ASGITransport(app=create_app(runtime_dir=tmp_path / "runtime"))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)
    return asyncio.run(run())


def test_home_links_and_scope(tmp_path):
    response = request("/", tmp_path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<html' in response.text
    assert '/assets/' in response.text or '/docs' in response.text


def test_sample_validation(tmp_path):
    response = request("/data/sample/validation", tmp_path)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"]
    assert data["row_counts"]["products.csv"] == 3
    assert data["errors"] == []
