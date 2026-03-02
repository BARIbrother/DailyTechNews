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
        content += f"{a['title']}\n{a['summary']}\n{a['link']}\n\n"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an MIT-level tech analyst."},
            {"role": "user", "content": f"Summarize these into 5 concise briefings:\n{content}"}
        ]
    )

    return response.choices[0].message.content


import smtplib
from email.mime.text import MIMEText
import os

def send_email(content):
    sender = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_PASSWORD"]
    receiver = sender

    msg = MIMEText(content)
    msg["Subject"] = "Daily Tech Briefing"
    msg["From"] = sender
    msg["To"] = receiver

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)


if __name__ == "__main__":
    news = get_news()
    summary = summarize(news)
    print(summary)
    send_email(summary)
