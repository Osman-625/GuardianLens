from fastapi.testclient import TestClient
from guardianlens.app import app
from guardianlens.capture import INVALID_LISTING_MESSAGE
from guardianlens.security import ensure_local_token
from conftest import data_url, image_bytes


def test_dashboard_available_while_startup_dataset_refresh_runs(isolated, monkeypatch):
    import asyncio
    import importlib
    import threading

    import httpx

    app_module = importlib.import_module("guardianlens.app")
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    refresh_finished = threading.Event()

    def slow_refresh(trigger):
        assert trigger == "application_startup"
        refresh_started.set()
        try:
            assert release_refresh.wait(timeout=10)
        finally:
            refresh_finished.set()

    monkeypatch.setattr(app_module, "refresh_annotation_dataset_safely", slow_refresh)

    async def check_startup():
        try:
            async with app_module.lifespan(app):
                try:
                    assert await asyncio.to_thread(refresh_started.wait, 2)
                    assert not refresh_finished.is_set()
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url="http://127.0.0.1:8770",
                    ) as client:
                        for path in ("/health", "/"):
                            response = await asyncio.wait_for(client.get(path), timeout=3)
                            assert response.status_code == 200
                    assert not refresh_finished.is_set()
                finally:
                    release_refresh.set()
        finally:
            release_refresh.set()
        assert refresh_finished.is_set()

    asyncio.run(check_startup())

def test_health_and_capture_auth(isolated):
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        payload={'platform':'carousell','source_url':'https://www.carousell.com.my/p/test-listing-123456/','page_title':'Test listing','screenshot_data_url':data_url(image_bytes()),'image_urls':['https://images.example.test/product.jpg'],'listing_evidence':{'h1_text':'Test listing','has_price_signal':True}}
        assert client.post('/api/capture',json=payload).status_code==401
        token=ensure_local_token();r=client.post('/api/capture',json=payload,headers={'X-GuardianLens-Token':token});assert r.status_code==200

def test_api_rejects_marketplace_homepage_with_explicit_message(isolated):
    with TestClient(app) as client:
        token=ensure_local_token()
        payload={'platform':'carousell','source_url':'https://www.carousell.com.my/','page_title':'Carousell','screenshot_data_url':data_url(image_bytes()),'image_urls':['https://images.example.test/product.jpg'],'listing_evidence':{'h1_text':'Carousell','has_price_signal':True}}
        response=client.post('/api/capture',json=payload,headers={'X-GuardianLens-Token':token})
        assert response.status_code==400
        assert response.json()['detail']==INVALID_LISTING_MESSAGE
