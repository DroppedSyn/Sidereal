import httpx

from tests.fake_ollama import FakeOllama


async def test_chat_returns_scripted_replies_in_order_and_records_requests():
    fake = FakeOllama(chat_replies=[{"relevance": 2}, "not json"])
    async with httpx.AsyncClient(transport=fake.transport(), base_url="http://ollama.test") as c:
        first = await c.post("/api/chat", json={"model": "m", "messages": []})
        second = await c.post("/api/chat", json={"model": "m", "messages": []})
        third = await c.post("/api/chat", json={"model": "m", "messages": []})
    assert first.json()["message"]["content"] == '{"relevance": 2}'
    assert second.json()["message"]["content"] == "not json"
    assert third.status_code == 500
    assert [b["model"] for b in fake.calls("/api/chat")] == ["m", "m", "m"]


async def test_tags_ps_and_unload():
    fake = FakeOllama(models=["a", "b"], loaded=["a"])
    async with httpx.AsyncClient(transport=fake.transport(), base_url="http://ollama.test") as c:
        tags = (await c.get("/api/tags")).json()
        await c.post("/api/generate", json={"model": "a", "keep_alive": 0})
        ps = (await c.get("/api/ps")).json()
    assert [m["name"] for m in tags["models"]] == ["a", "b"]
    assert ps["models"] == []
