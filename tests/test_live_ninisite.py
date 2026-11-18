import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_live_forums_and_topics(client):
    f = (await client.call_tool("nn_forums", {})).structured_content
    assert len(f["categories"]) >= 15 and any(x["id"] == 6 for c in f["categories"] for x in c["forums"])
    t = (await client.call_tool("nn_forum_topics", {"forum_id": 6})).structured_content
    assert t["topic_count"] > 100000 and len(t["topics"]) >= 25
    top = (await client.call_tool("nn_topic", {"topic_id": t["topics"][-1]["id"]})).structured_content
    assert top["title"] and top["opening_post"]["text"]


async def test_live_hot(client):
    r = (await client.call_tool("nn_hot_topics", {})).structured_content
    assert len(r["topics"]) >= 20 and r["topics"][0]["replies"] > 10


async def test_live_articles(client):
    c = (await client.call_tool("nn_article_categories", {})).structured_content
    assert len(c["categories"]) >= 10
    a = (await client.call_tool("nn_articles", {"category_id": c["categories"][0]["id"]})).structured_content
    assert len(a["articles"]) == 12
    r = (await client.call_tool("nn_article", {"article_id": a["articles"][0]["id"]})).structured_content
    assert r["title"] and len(r["text"]) > 300


async def test_live_pregnancy_week(client):
    r = (await client.call_tool("nn_pregnancy_week", {"week": 20})).structured_content
    assert "بیستم" in r["title"] and len(r["sections"]) >= 8
