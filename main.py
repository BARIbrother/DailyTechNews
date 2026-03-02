import feedparser
from openai import OpenAI
import os
from datetime import datetime, timedelta

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

RSS_URL = "https://news.google.com/rss/search?q=AI+OR+quantum+computing+OR+semiconductor&hl=en-US&gl=US&ceid=US:en"


def get_news():
    feed = feedparser.parse(RSS_URL)
    yesterday = datetime.utcnow() - timedelta(days=1)
    articles = []

    for entry in feed.entries[:10]:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "summary": entry.summary
        })

    return articles[:5]


def summarize(articles):
    content = ""
    for a in articles:
        content += f"""
        제목: {a['title']}
        요약: {a['summary']}
        링크: {a['link']}

        """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "당신은 MIT 수준의 테크 전문 애널리스트입니다."
            },
            {
                "role": "user",
                "content": f"""
    아래 뉴스 기사 5개를 한국어로 심층 요약하시오.

    각 기사마다 반드시 다음 구조를 지켜라:

    1️⃣ 제목 (굵게 표시)
    2️⃣ 핵심 내용 요약 (4~6문장)
    3️⃣ 기술적 의미 (AI/양자/반도체 관점)   
    4️⃣ 산업적/투자적 의미
    5️⃣ 원문 기사 링크

    전체 분량은 충분히 상세하게 작성하되,
    각 기사당 최소 8~12문장 이상 작성하시오.

    기사 목록:
    {content}
    """
            }
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content


import smtplib
from email.mime.text import MIMEText
import os

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_email(content):
    sender = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_PASSWORD"]
    receiver = sender

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "📰 Daily Tech Briefing (KOR)"
    msg["From"] = sender
    msg["To"] = receiver

    html_content = content.replace("\n", "<br>")
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)

if __name__ == "__main__":
    news = get_news()
    summary = summarize(news)
    print(summary)
    send_email(summary)
