import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import requests
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

RSS_URL = "https://news.google.com/rss/search?q=AI+OR+quantum+computing+OR+semiconductor&hl=en-US&gl=US&ceid=US:en"
HTTP_HEADERS = {"User-Agent": "DailyTechNews/1.0 (GitHub Actions)"}
HTTP_TIMEOUT = 20


def fetch_json(url):
    response = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


# 1️⃣ Google News
def get_google_news():
    try:
        response = requests.get(RSS_URL, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except requests.RequestException as exc:
        print(f"Google News fetch failed: {exc}")
        return []

    articles = []
    for entry in feed.entries[:30]:
        articles.append({
            "title": entry.get("title", "").strip(),
            "link": entry.get("link", ""),
            "summary": entry.get("summary", ""),
            "score": 0,
        })
    return [a for a in articles if a["title"]]


# 2️⃣ Hacker News
def get_hackernews():
    try:
        ids = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    except requests.RequestException as exc:
        print(f"Hacker News list fetch failed: {exc}")
        return []

    articles = []
    for story_id in ids[:30]:
        try:
            item = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        except requests.RequestException as exc:
            print(f"Hacker News item {story_id} failed: {exc}")
            continue

        if not item or "title" not in item:
            continue

        articles.append({
            "title": item["title"],
            "link": item.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
            "summary": "",
            "score": item.get("score", 0) + item.get("descendants", 0),
        })

    return articles


# 3️⃣ 통합 + 간단 랭킹
def merge_and_rank(g_news, hn_news):
    combined = g_news + hn_news

    seen = set()
    unique = []
    for a in combined:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)

    unique.sort(key=lambda x: x["score"], reverse=True)
    return unique[:30]


# 4️⃣ GPT 최종 선정
def select_top_articles(articles):
    if len(articles) <= 5:
        return articles

    content = ""
    for i, a in enumerate(articles, start=1):
        content += f"{i}. {a['title']}\n"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "당신은 글로벌 테크 산업 분석가입니다."},
            {"role": "user", "content": f"""
다음 뉴스 중 가장 중요하고 영향력 있는 5개를 선택하시오.

기준:
- 기술 혁신성
- 산업 영향력
- 장기적 중요성

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


# 5️⃣ 요약
def summarize(articles):
    content = ""
    for a in articles:
        content += f"""
제목: {a['title']}
링크: {a['link']}
"""

    response = client.chat.completions.create(
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


# 6️⃣ 이메일 전송
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
    g_news = get_google_news()
    hn_news = get_hackernews()
    print(f"Fetched Google News={len(g_news)}, Hacker News={len(hn_news)}")

    merged = merge_and_rank(g_news, hn_news)
    if not merged:
        raise RuntimeError("뉴스를 하나도 가져오지 못했습니다.")

    top = select_top_articles(merged)
    print("Selected:")
    for article in top:
        print(f"- {article['title']}")

    summary = summarize(top)
    send_email(summary)
    print("Email sent.")
