import math
import os
import re
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

import feedparser
import requests
from openai import OpenAI

HTTP_HEADERS = {"User-Agent": "DailyTechNews/1.0 (GitHub Actions)"}
HTTP_TIMEOUT = 20
HN_WINDOW_HOURS = 48
CANDIDATE_LIMIT = 30

TOPIC_PATTERN = re.compile(
    r"\b("
    r"ai|a\.i\.|artificial intelligence|machine learning|deep learning|"
    r"llm|gpt|openai|anthropic|quantum|qubit|"
    r"semiconductor|chip|chips|gpu|nvidia|tsmc|asml|"
    r"foundry|wafer|hbm|lithography|neural|transformer"
    r")\b",
    re.I,
)

RSS_SOURCES = [
    {
        "name": "IEEE Spectrum",
        "url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
        "weight": 8.5,
        "require_topic": False,
    },
    {
        "name": "IEEE Spectrum",
        "url": "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        "weight": 8.5,
        "require_topic": False,
    },
    {
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "weight": 8.5,
        "require_topic": True,
    },
    {
        "name": "Nature",
        "url": "https://www.nature.com/nature.rss",
        "weight": 9.0,
        "require_topic": True,
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "weight": 7.5,
        "require_topic": True,
    },
]

HN_QUERIES = [
    "artificial intelligence",
    "quantum computing",
    "semiconductor",
    "NVIDIA GPU",
    "TSMC",
]


def openai_client():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def fetch_json(url):
    response = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


def is_on_topic(text):
    return bool(TOPIC_PATTERN.search(text or ""))


def parse_entry_time(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return datetime.now(timezone.utc)
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def age_hours(dt):
    return max((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 0.0)


def recency_multiplier(hours):
    return 1.0 / (1.0 + hours / 24.0)


def editorial_score(weight, hours, comments=0):
    return weight * 12.0 * recency_multiplier(hours) + min(comments, 80) * 0.25


def hn_hot_score(points, comments, hours):
    heat = (max(points, 1) + 0.4 * comments) / math.pow(hours + 2.0, 1.8)
    return heat * 20.0


def make_article(title, link, source, score, summary=""):
    return {
        "title": title.strip(),
        "link": link,
        "source": source,
        "summary": summary,
        "score": round(score, 2),
    }


def get_editorial_news():
    articles = []
    for source in RSS_SOURCES:
        try:
            response = requests.get(source["url"], headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            print(f"{source['name']} fetch failed: {exc}")
            continue

        count = 0
        for entry in feed.entries[:20]:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or ""
            if not title:
                continue
            blob = f"{title} {entry.get('summary', '')}"
            if source["require_topic"] and not is_on_topic(blob):
                continue
            try:
                comments = int(entry.get("slash_comments") or 0)
            except (TypeError, ValueError):
                comments = 0
            hours = age_hours(parse_entry_time(entry))
            articles.append(
                make_article(
                    title,
                    link,
                    source["name"],
                    editorial_score(source["weight"], hours, comments),
                    entry.get("summary", ""),
                )
            )
            count += 1
        print(f"{source['name']}: {count} on-topic items")
    return articles


def get_hackernews():
    since = int(time.time()) - HN_WINDOW_HOURS * 3600
    hits = {}

    def add_hit(hit):
        object_id = str(hit.get("objectID") or "")
        title = (hit.get("title") or "").strip()
        if not object_id or not title or not is_on_topic(title):
            return
        hits[object_id] = hit

    try:
        front = fetch_json("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=50")
        for hit in front.get("hits", []):
            add_hit(hit)
    except requests.RequestException as exc:
        print(f"Hacker News front page fetch failed: {exc}")

    for query in HN_QUERIES:
        url = (
            "https://hn.algolia.com/api/v1/search"
            f"?query={quote(query)}&tags=story&hitsPerPage=20"
            f"&numericFilters=created_at_i>{since}"
        )
        try:
            payload = fetch_json(url)
        except requests.RequestException as exc:
            print(f"Hacker News search '{query}' failed: {exc}")
            continue
        for hit in payload.get("hits", []):
            add_hit(hit)

    articles = []
    for object_id, hit in hits.items():
        points = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        created = int(hit.get("created_at_i") or time.time())
        hours = age_hours(datetime.fromtimestamp(created, tz=timezone.utc))
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        articles.append(
            make_article(
                hit["title"],
                link,
                "Hacker News",
                hn_hot_score(points, comments, hours),
            )
        )

    print(f"Hacker News: {len(articles)} on-topic items")
    return articles


def merge_and_rank(editorial, hn_news):
    combined = editorial + hn_news
    seen = set()
    unique = []
    for article in combined:
        key = article["title"].casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(article)
    unique.sort(key=lambda item: item["score"], reverse=True)
    return unique[:CANDIDATE_LIMIT]


def select_top_articles(articles):
    if len(articles) <= 5:
        return articles

    content = ""
    for i, article in enumerate(articles, start=1):
        content += (
            f"{i}. [{article['source']} | heat {article['score']}] {article['title']}\n"
        )

    response = openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "당신은 글로벌 테크 산업 분석가입니다."},
            {"role": "user", "content": f"""
다음 뉴스 중 가장 중요하고 영향력 있는 5개를 선택하시오.

기준:
- 기술 혁신성
- 산업 영향력
- 장기적 중요성
- 최근 화제성 (heat가 높을수록 더 뜨거움)
- 출처 신뢰도 (IEEE, Nature, MIT TR, Ars가 HN보다 공신력 있음)

출력은 번호 5개만. 예: [1, 4, 7, 12, 20]

뉴스:
{content}
"""}
        ],
        temperature=0.3,
    )

    raw = response.choices[0].message.content or ""
    print(f"GPT selection: {raw}")

    selected = []
    seen = set()
    for index in map(int, re.findall(r"\d+", raw)):
        if 1 <= index <= len(articles) and index not in seen:
            seen.add(index)
            selected.append(articles[index - 1])
        if len(selected) == 5:
            break

    if len(selected) < 5:
        print("GPT selection incomplete; filling with ranked articles")
        for article in articles:
            if article not in selected:
                selected.append(article)
            if len(selected) == 5:
                break

    return selected[:5]


def summarize(articles):
    content = ""
    for article in articles:
        content += f"""
제목: {article['title']}
출처: {article['source']}
링크: {article['link']}
"""

    response = openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "당신은 MIT 수준의 테크 분석가입니다."},
            {"role": "user", "content": f"""
다음 뉴스들을 한국어로 심층 분석하시오.

각 뉴스마다:
1. 제목
2. 핵심 요약
3. 기술적 의미
4. 산업적 영향
5. 링크

충분히 자세히 작성하시오.

뉴스:
{content}
"""}
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content


def send_email(content):
    sender = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🔥 Hybrid Tech Briefing"
    msg["From"] = sender
    msg["To"] = sender

    html_content = content.replace("\n", "<br>")
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)


if __name__ == "__main__":
    editorial = get_editorial_news()
    hn_news = get_hackernews()
    print(f"Fetched editorial={len(editorial)}, Hacker News={len(hn_news)}")

    merged = merge_and_rank(editorial, hn_news)
    if not merged:
        raise RuntimeError("뉴스를 하나도 가져오지 못했습니다.")

    print("Ranked candidates:")
    for article in merged[:10]:
        print(f"- {article['score']:6.1f} [{article['source']}] {article['title']}")

    top = select_top_articles(merged)
    print("Selected:")
    for article in top:
        print(f"- [{article['source']}] {article['title']}")

    summary = summarize(top)
    send_email(summary)
    print("Email sent.")
