import feedparser
import requests
from openai import OpenAI
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

RSS_URL = "https://news.google.com/rss/search?q=AI+OR+quantum+computing+OR+semiconductor&hl=en-US&gl=US&ceid=US:en"

# 1️⃣ Google News
def get_google_news():
    feed = feedparser.parse(RSS_URL)
    articles = []

    for entry in feed.entries[:30]:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "summary": entry.summary,
            "score": 0  # 초기 점수
        })

    return articles


# 2️⃣ Hacker News
def get_hackernews():
    ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json").json()
    articles = []

    for i in ids[:30]:
        item = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json").json()

        if item and "title" in item:
            articles.append({
                "title": item["title"],
                "link": item.get("url", ""),
                "summary": "",
                "score": item.get("score", 0) + item.get("descendants", 0)
            })

    return articles


# 3️⃣ 통합 + 간단 랭킹
def merge_and_rank(g_news, hn_news):
    combined = g_news + hn_news

    # 제목 기준 중복 제거
    seen = set()
    unique = []
    for a in combined:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)

    # score 기준 정렬 (HN가 우선)
    unique.sort(key=lambda x: x["score"], reverse=True)

    return unique[:30]  # 상위 30개만


# 4️⃣ GPT 최종 선정
def select_top_articles(articles):
    content = ""
    for i, a in enumerate(articles):
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

출력:
[번호, 번호, 번호, 번호, 번호]

뉴스:
{content}
"""}
        ],
        temperature=0.3
    )

    import re
    indices = list(map(int, re.findall(r'\d+', response.choices[0].message.content)))

    return [articles[i] for i in indices if i < len(articles)][:5]


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
        temperature=0.7
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


# 실행
if __name__ == "__main__":
    g_news = get_google_news()
    hn_news = get_hackernews()

    merged = merge_and_rank(g_news, hn_news)
    top = select_top_articles(merged)

    summary = summarize(top)
    send_email(summary)