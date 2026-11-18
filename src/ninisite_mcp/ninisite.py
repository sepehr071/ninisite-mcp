"""Ninisite tools: forums, topic lists, topics with replies, articles, article categories, pregnancy weeks."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import unquote

from bs4 import BeautifulSoup
from bs4.element import Tag
from pydantic import Field

from .http import ApiError, fetch
from .registry import tool

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
MAX_TEXT = 6000  # characters per post or article body returned
MAX_WEEK_TEXT = 14000

Page = Annotated[int, Field(description="Page, 1-based.", ge=1, le=100000)]


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _txt(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _body(el: Tag | None, limit: int = MAX_TEXT) -> str:
    """Readable text of a post or article body: line breaks kept, scripts and images dropped, capped at `limit`."""
    if el is None:
        return ""
    for t in el.select("script, style, img, iframe, video, noscript"):
        t.decompose()
    for br in el.find_all("br"):
        br.replace_with("\n")
    for q in el.find_all("blockquote"):
        q.insert_before("\n> ")
    for b in el.find_all(["p", "div", "li", "blockquote", "h2", "h3", "h4", "tr"]):
        b.append("\n")
    text = el.get_text("")
    text = re.sub(r"[ \t\xa0\r]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _num(s: str) -> int | None:
    m = re.search(r"\d[\d,]*", s.translate(FA_DIGITS))
    return int(m.group().replace(",", "")) if m else None


def _last_page(soup: BeautifulSoup) -> int:
    pages = [int(a.get_text(strip=True)) for a in soup.select(".pagination a") if a.get_text(strip=True).isdigit()]
    return max(pages, default=1)


def _page_params(page: int) -> list[tuple[str, str]]:
    return [("page", str(page))] if page > 1 else []


def _iso(s: str | None) -> str | None:
    """The site's "2/28/2026 11:00:00 AM" (US style) as ISO 8601; other formats pass through."""
    try:
        return datetime.strptime(s or "", "%m/%d/%Y %I:%M:%S %p").isoformat()
    except ValueError:
        return s


def _id_in(href: str, kind: str) -> int | None:
    m = re.search(rf"/{kind}/(\d+)", href)
    return int(m.group(1)) if m else None


def _title(soup: BeautifulSoup) -> str:
    return _txt(soup.select_one("h1"))


@tool("Forums and categories")
async def nn_forums() -> dict:
    """List every forum category and its forums (id and name) on ninisite.com/discussion."""
    _, html = await fetch("/discussion")
    out = []
    for table in _soup(html).select(".category-table"):
        head = table.select_one("h2 a[href]")
        cid = _id_in(head["href"], "discussion") if head else None
        if cid is None:
            continue
        forums = []
        for a in table.select('a[href*="/discussion/forum/"]'):
            fid = _id_in(a["href"], "forum")
            if fid is not None and not any(f["id"] == fid for f in forums):
                forums.append({"id": fid, "name": _txt(a)})
        out.append({"id": cid, "name": re.sub(r"\s*-\s*\d+\s*تالار\s*$", "", _txt(head)), "forums": forums})
    if not out:
        raise ApiError("Ninisite forum index had no categories; the page layout may have changed.")
    return {"categories": out}


def _topic_rows(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for r in soup.select(".category--item"):
        a = r.select_one('a[href*="/discussion/topic/"]')
        tid = _id_in(a["href"], "topic") if a else None
        if tid is None:
            continue
        counts = r.select(".topic_number")
        last = r.select_one(".last-topic")
        date, time_ = (
            _txt(last.select_one(".last-topic-date")) if last else "",
            _txt(last.select_one(".last-topic-time") if last else None),
        )
        rows.append(
            {
                "id": tid,
                "title": _txt(r.select_one(".topic_subject")),
                "author": _txt(r.select_one(".last-topic-user a")),
                "replies": _num(_txt(counts[0])) if counts else None,
                "pinned": bool(r.select_one(".iconpin")) or None,
                "last_reply": " ".join(p for p in (date.strip("-").strip(), time_.strip("-").strip()) if p) or None,
            }
        )
    return rows


@tool("Forum topics")
async def nn_forum_topics(
    forum_id: Annotated[int, Field(description="Forum id from nn_forums, e.g. 6.", ge=1, le=100000)],
    page: Page = 1,
) -> dict:
    """List the topics of one forum, most recently active first; pinned admin topics come first on page 1."""
    url, html = await fetch(f"/discussion/forum/{forum_id}", _page_params(page))
    soup = _soup(html)
    rows = _topic_rows(soup)
    if not rows and page == 1:
        raise ApiError(f"Forum {forum_id} has no topics or does not exist.", 404)
    count = _num(_txt(soup.select_one(".table-forum__title h1 + span")))
    return {
        "forum": _txt(soup.select_one(".table-forum__title h1")),
        "topic_count": count,
        "page": page,
        "pages": _last_page(soup),
        "topics": rows,
    }


@tool("Hot and updated topics")
async def nn_hot_topics(
    feed: Annotated[
        Literal["hottest", "updated"],
        Field(description="hottest: most active in the last two days; updated: newest replies."),
    ] = "hottest",
    page: Page = 1,
) -> dict:
    """List the site-wide hottest or recently updated forum topics."""
    _, html = await fetch(f"/discussion/topics/{feed}", _page_params(page))
    soup = _soup(html)
    return {"feed": feed, "page": page, "pages": _last_page(soup), "topics": _topic_rows(soup)}


def _post(art: Tag) -> dict:
    return {
        "id": int(art["id"][5:]) if art["id"][5:].isdigit() else None,
        "author": _txt(art.select_one(".nickname")),
        "badges": [_txt(s) for s in art.select(".topic-post__user-info .icon span")] or None,
        "date": _txt(art.select_one(".created-post .date")),
        "time": _txt(art.select_one(".created-post .time")),
        "text": _body(art.select_one(".topic-post__message")),
    }


@tool("Topic with replies")
async def nn_topic(
    topic_id: Annotated[int, Field(description="Topic id from nn_forum_topics or nn_hot_topics.", ge=1, le=10**10)],
    page: Page = 1,
) -> dict:
    """Read a forum topic: the opening post plus one page of replies (about 15 posts per page)."""
    _, html = await fetch(f"/discussion/topic/{topic_id}", _page_params(page))
    soup = _soup(html)
    first = soup.select_one("article#topic")
    if first is None:
        raise ApiError(f"Topic {topic_id} not found or has no readable post.", 404)
    crumbs = [_txt(s) for s in soup.select(".breadcrumb [itemprop=name]")]
    stats = _txt(first.select_one(".date-time"))
    views = re.search(r"([\d,]+)\s*بازدید", stats.translate(FA_DIGITS))
    posts = re.search(r"([\d,]+)\s*پست", stats.translate(FA_DIGITS))
    replies = [_post(a) for a in soup.select("article[id^=post-]")]
    out: dict = {"id": topic_id, "title": _title(soup)}
    if page == 1:
        out["opening_post"] = _post(first)
    out |= {
        "forum": crumbs[-2] if len(crumbs) > 2 else None,
        "views": int(views.group(1).replace(",", "")) if views else None,
        "post_count": int(posts.group(1).replace(",", "")) if posts else None,
        "page": page,
        "has_next_page": soup.select_one('.pagination a[title="Next page"]') is not None,
        "replies": replies,
    }
    return out


@tool("Article categories")
async def nn_article_categories(
    category_id: Annotated[
        int | None,
        Field(
            description="Top-level category id (from the top-level list) to list its sub-categories; omit for the top level."
        ),
    ] = None,
) -> dict:
    """List magazine article categories (ids for nn_articles); pass a top-level id to see its sub-categories."""
    _, html = await fetch(f"/articles/{category_id}" if category_id else "/articles/latest")
    soup = _soup(html)
    if category_id is None:
        seen = {}
        for a in soup.select(".menu-wrapper a[href^='/articles/']"):
            cid = _id_in(a["href"], "articles")
            if cid is not None:
                seen.setdefault(cid, _txt(a))
        return {"categories": [{"id": k, "name": v} for k, v in seen.items()]}
    groups = []
    for col in soup.select(".row.m-t-2.m-b-2 > div"):
        links = [(_id_in(a["href"], "articles"), _txt(a)) for a in col.select("a[href^='/articles/']")]
        if links and links[0][0] is not None:
            groups.append(
                {"id": links[0][0], "name": links[0][1], "children": [{"id": i, "name": n} for i, n in links[1:]]}
            )
    return {"category": category_id, "subcategories": groups}


@tool("Articles list")
async def nn_articles(
    category_id: Annotated[
        int | None, Field(description="Category or sub-category id from nn_article_categories; omit for the newest.")
    ] = None,
    page: Page = 1,
) -> dict:
    """List magazine articles, newest first, for all categories or one category."""
    _, html = await fetch(f"/articles/{category_id}" if category_id else "/articles/latest", _page_params(page))
    soup = _soup(html)
    arts = []
    for c in soup.select(".articles-new .card"):
        a = c.select_one("a.article__link[href*='/article/']")
        aid = _id_in(a["href"], "article") if a else None
        if aid is None:
            continue
        detail = c.select_one(".detail:not(.view)")
        arts.append(
            {
                "id": aid,
                "title": _txt(c.select_one(".card-title")),
                "age": _txt(detail) or None,
                "views": _num(_txt(c.select_one(".detail.view"))),
            }
        )
    return {"page": page, "pages": _last_page(soup), "articles": arts}


@tool("Read article")
async def nn_article(
    article_id: Annotated[int, Field(description="Article id from nn_articles, e.g. 21090.", ge=1, le=10**8)],
    comments: Annotated[bool, Field(description="Also return the first reader comments.")] = False,
) -> dict:
    """Read one magazine article: title, date, tags, text and counts."""
    _, html = await fetch(f"/article/{article_id}")
    soup = _soup(html)
    body = soup.select_one(".article-paragraph")
    if body is None:
        raise ApiError(f"Article {article_id} not found or has no readable text.", 404)
    pub = soup.select_one("meta[itemprop=datePublished]")
    meta = {m.get("property"): m.get("content") for m in soup.select("meta[property^='article:']") if m.get("property")}
    like = soup.select_one(".likeCount")
    out = {
        "id": article_id,
        "title": _title(soup),
        "author": _txt(soup.select_one(".article__post--item [itemprop=author]")),
        "published": _iso(pub.get("content") if pub else meta.get("article:published_time")),
        "age": _txt(pub.parent) if pub and pub.parent else None,
        "views": _num(_txt(soup.select_one(".comment__view span:last-child"))),
        "likes": _num(_txt(like)),
        "comment_count": _num(_txt(soup.select_one(".comment__num"))),
        "tags": [m.get("content") for m in soup.select("meta[property='article:tag']")] or None,
        "text": _body(body, MAX_TEXT * 2),
    }
    if comments:
        out["comments"] = [
            {
                "author": _txt(c.select_one(".nick-name, .nickname, [itemprop=name]")),
                "text": _body(c.select_one(".comment__content"), 1500),
            }
            for c in soup.select(".comment.m-b-1")[:10]
        ]
    return out


async def _week_slugs() -> dict[int, str]:
    _, html = await fetch("/timeline/pregnancy")
    slugs: dict[int, str] = {}
    for a in _soup(html).select("a[href^='/timeline/']"):
        t = _txt(a)
        if t.isdigit() and "?" not in a["href"]:
            slugs.setdefault(int(t), a["href"])
    return slugs


@tool("Pregnancy week")
async def nn_pregnancy_week(
    week: Annotated[int, Field(description="Pregnancy week, 1 to 40.", ge=1, le=40)],
    section: Annotated[
        str | None, Field(description="Only sections whose heading contains this Persian word, e.g. تغذیه or علائم.")
    ] = None,
) -> dict:
    """Read the week-by-week pregnancy guide for one week: symptoms, nutrition, fetus size, care, checklist."""
    slugs = await _week_slugs()
    if week not in slugs:
        raise ApiError(f"Ninisite has no page for pregnancy week {week}.", 404)
    _, html = await fetch(unquote(slugs[week]))
    soup = _soup(html)
    art = soup.select_one("article.article_content")
    if art is None:
        raise ApiError(f"Pregnancy week {week} page has no readable text.", 404)
    for t in art.select("script, style, img, iframe, noscript"):
        t.decompose()
    parts: list[tuple[str, list[str]]] = [("", [])]
    for el in art.find_all(["h2", "h3", "p", "ul", "ol", "table"]):
        if el.name in ("h2", "h3"):
            parts.append((_txt(el), []))
        elif el.find_parent(["ul", "ol", "table"]) is None:
            t = _body(el, 3000)
            if t:
                parts[-1][1].append(t)
    sections = [{"heading": h, "text": "\n".join(ts)} for h, ts in parts if ts and h != "فهرست مطالب"]
    if section:
        sections = [s for s in sections if section in s["heading"]]
    total = 0
    for s in sections:
        s["text"] = s["text"][: max(0, MAX_WEEK_TEXT - total)]
        total += len(s["text"])
    return {"week": week, "title": _title(soup), "sections": [s for s in sections if s["text"]]}
