import pytest

from ninisite_mcp import http

pytestmark = pytest.mark.anyio


async def test_forums(client, site):
    site["/discussion"] = "discussion.html"
    r = (await client.call_tool("nn_forums", {})).structured_content
    assert len(r["categories"]) == 3
    c = r["categories"][0]
    assert c["id"] == 15 and c["name"] == "مدیر سایت" and c["forums"][0] == {"id": 85, "name": "سخن مدیر سایت"}


async def test_forum_topics(client, site):
    site["/discussion/forum/6"] = "forum_6.html"
    r = (await client.call_tool("nn_forum_topics", {"forum_id": 6})).structured_content
    assert r["forum"] == "رشد و تکامل جنین و سیر بارداری" and r["topic_count"] > 1000 and r["pages"] > 1
    assert len(r["topics"]) == 8
    pinned = r["topics"][0]
    assert pinned["pinned"] is True and pinned["id"] == 18925417 and pinned["author"]
    assert all(t["id"] and t["title"] for t in r["topics"])


async def test_forum_page_param_and_redirect_keeps_page(client, site):
    def slug(request):
        if request.url.path == "/discussion/forum/6":
            return http.httpx.Response(301, headers={"location": "/discussion/forum/6/x?page=2"})

    site["/discussion/forum/6"] = slug
    site["/discussion/forum/6/x"] = "forum_6.html"
    r = (await client.call_tool("nn_forum_topics", {"forum_id": 6, "page": 2})).structured_content
    assert r["page"] == 2 and site.calls[-1].url.params["page"] == "2"


async def test_hot_topics(client, site):
    site["/discussion/topics/updated"] = "hottest.html"
    r = (await client.call_tool("nn_hot_topics", {"feed": "updated"})).structured_content
    assert r["feed"] == "updated" and r["topics"][0]["replies"] > 100 and r["topics"][0]["last_reply"]


async def test_topic(client, site):
    site["/discussion/topic/19098487"] = "topic_19098487.html"
    r = (await client.call_tool("nn_topic", {"topic_id": 19098487})).structured_content
    assert r["title"].startswith("یکی") and r["forum"] == "بیماریهای کودکان" and r["views"] >= 100
    assert r["opening_post"]["author"] == "نیتروگلیسیرین" and "تعقیب" not in r["opening_post"]["text"][:3]
    assert r["replies"][0]["author"] == "kiana_re" and r["replies"][0]["date"] == "1405/08/27"
    assert r["has_next_page"] is True and len(r["replies"]) == 6
    assert r["post_count"] >= 7 and "reply_count" not in r
    # no personal fields leak
    assert set(r["replies"][0]) <= {"id", "author", "badges", "date", "time", "text"}


async def test_topic_page2_has_no_opening_post(client, site):
    site["/discussion/topic/19098487"] = "topic_19098487.html"
    r = (await client.call_tool("nn_topic", {"topic_id": 19098487, "page": 2})).structured_content
    assert "opening_post" not in r and site.calls[0].url.params["page"] == "2"


async def test_article_categories(client, site):
    site["/articles/latest"] = "articles_latest.html"
    site["/articles/48"] = "articles_48.html"
    top = (await client.call_tool("nn_article_categories", {})).structured_content
    assert top["categories"][0] == {"id": 48, "name": "بارداری و اقدام"} and len(top["categories"]) == 11
    sub = (await client.call_tool("nn_article_categories", {"category_id": 48})).structured_content
    assert [g["id"] for g in sub["subcategories"]] == [54, 55, 56]
    assert {"id": 95, "name": "پزشکی"} in sub["subcategories"][0]["children"]


async def test_articles_list_skips_sidebar(client, site):
    site["/articles/latest"] = "articles_latest.html"
    r = (await client.call_tool("nn_articles", {})).structured_content
    assert r["pages"] > 100 and len(r["articles"]) == 5
    assert r["articles"][0]["id"] == 21091 and r["articles"][0]["age"] and r["articles"][0]["views"] is not None


async def test_article(client, site):
    site["/article/21090"] = "article_21090.html"
    r = (await client.call_tool("nn_article", {"article_id": 21090, "comments": True})).structured_content
    assert r["title"].startswith("به بهانه") and r["views"] > 1000 and r["comment_count"] == 8
    assert r["tags"][0] == "رابطه پدر و دختر" and r["text"].startswith("نی نی سایت:") and len(r["text"]) > 1000
    assert len(r["comments"]) == 3 and r["comments"][0]["text"]


def test_iso_date():
    from ninisite_mcp.ninisite import _iso

    assert _iso("2/28/2026 11:00:00 AM") == "2026-02-28T11:00:00"
    assert _iso("11/17/2026 3:05:09 PM") == "2026-11-17T15:05:09"
    assert _iso("1405/08/27") == "1405/08/27" and _iso(None) is None


async def test_article_published_is_iso(client, site):
    site["/article/21090"] = "article_21090.html"
    r = (await client.call_tool("nn_article", {"article_id": 21090})).structured_content
    assert r["published"][:2] == "20" and "T" in r["published"] and "AM" not in r["published"]


async def test_topic_past_last_page_is_empty_not_error(client, site):
    import re

    from conftest import page

    def strip_replies(request):
        html = page("topic_19098487.html")
        return http.httpx.Response(
            200, text=re.sub(r"<article [^>]*id=\"post-\d+\".*?</article>", "", html, flags=re.S)
        )

    site["/discussion/topic/19098487"] = strip_replies
    r = (await client.call_tool("nn_topic", {"topic_id": 19098487, "page": 99})).structured_content
    assert r["replies"] == [] and "opening_post" not in r


async def test_pregnancy_week(client, site):
    site["/timeline/pregnancy"] = "timeline_pregnancy.html"
    site["/timeline/هفته-اول-بارداری"] = "timeline_week1.html"
    r = (await client.call_tool("nn_pregnancy_week", {"week": 1})).structured_content
    heads = [s.get("heading") for s in r["sections"]]
    assert r["title"] == "هفته اول بارداری" and "تغذیه هفته‌ی اول بارداری" in heads
    only = (await client.call_tool("nn_pregnancy_week", {"week": 1, "section": "تغذیه"})).structured_content
    assert [s["heading"] for s in only["sections"]] == ["تغذیه هفته‌ی اول بارداری"]


async def test_410_message(client, site):
    site["/discussion/forum/999"] = lambda r: http.httpx.Response(410)
    r = await client.call_tool("nn_forum_topics", {"forum_id": 999})
    assert r.is_error and "HTTP 410" in r.content[0].text


async def test_host_allowlist(site):
    with pytest.raises(http.ApiError):
        await http.fetch("https://example.com/")


async def test_tools_listed_with_read_only(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == {
        "nn_forums", "nn_forum_topics", "nn_hot_topics", "nn_topic", "nn_article_categories",
        "nn_articles", "nn_article", "nn_pregnancy_week",
    }  # fmt: skip
    assert all(t.annotations.read_only_hint for t in tools)
