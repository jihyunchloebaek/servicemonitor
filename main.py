import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

KST = ZoneInfo("Asia/Seoul")

def now_kst():
    return datetime.now(KST)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

SERVICES = [
    {"id": "skt",     "name": "SKT",     "emoji": "🔷", "keywords": ["SKT 불통", "SKT 먹통", "SKT 접속 안됨", "SKT 멈춤", "SKT 장애 발생"]},
    {"id": "kt",      "name": "KT",      "emoji": "🔴", "keywords": ["KT 불통", "KT 먹통", "KT 접속 안됨", "KT 멈춤", "KT 장애 발생"]},
    {"id": "lgu",     "name": "LGU+",    "emoji": "💜", "keywords": ["유플러스 불통", "유플러스 먹통", "유플러스 접속 안됨", "유플러스 멈춤", "유플러스 장애 발생"]},
    {"id": "netflix", "name": "넷플릭스", "emoji": "🎬", "keywords": ["넷플릭스 불통", "넷플릭스 먹통", "넷플릭스 접속 안됨", "넷플릭스 멈춤"]},
    {"id": "wavve",   "name": "웨이브",   "emoji": "🌊", "keywords": ["웨이브 불통", "웨이브 먹통", "웨이브 접속 안됨", "웨이브 멈춤"]},
    {"id": "tving",   "name": "티빙",     "emoji": "📺", "keywords": ["티빙 불통", "티빙 먹통", "티빙 접속 안됨", "티빙 멈춤"]},
    {"id": "naver",   "name": "네이버",   "emoji": "🟢", "keywords": ["네이버 불통", "네이버 먹통", "네이버 접속 안됨", "네이버 멈춤"]},
    {"id": "kakao",   "name": "카카오",   "emoji": "🟡", "keywords": ["카카오톡 불통", "카카오 먹통", "카카오 접속 안됨", "카카오 멈춤"]},
]

monitor_cache: dict = {
    "results": None,
    "checked_at": None,
}


async def check_service(service: dict) -> dict:
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    articles = []
    is_down = False

    for keyword in service["keywords"][:2]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    headers=headers,
                    params={"query": keyword, "display": 3, "sort": "date"},
                )
                if resp.is_success:
                    for item in resp.json().get("items", []):
                        try:
                            # 제목에서만 키워드 감지
                            title = item.get("title", "").replace("<b>","").replace("</b>","")
                            title_has_keyword = any(kw in title for kw in service["keywords"])
                            if not title_has_keyword:
                                continue
                            pub_dt = parsedate_to_datetime(item.get("pubDate", ""))
                            age_min = (datetime.now(pub_dt.tzinfo) - pub_dt).total_seconds() / 60
                            if age_min <= 60:
                                is_down = True
                                articles.append({
                                    "title": title,
                                    "link": item.get("link", ""),
                                    "pubDate": item.get("pubDate", ""),
                                })
                        except Exception:
                            pass
        except Exception as e:
            print(f"네이버 API 오류 ({keyword}): {e}")

    return {
        "id": service["id"],
        "name": service["name"],
        "emoji": service["emoji"],
        "status": "down" if is_down else "normal",
        "articles": articles[:3],
    }


async def monitor_task():
    print(f"[{now_kst()}] 장애 모니터링 시작...")
    results = [await check_service(s) for s in SERVICES]
    monitor_cache["results"] = results
    monitor_cache["checked_at"] = now_kst().isoformat()
    down = [r["name"] for r in results if r["status"] == "down"]
    print(f"[{now_kst()}] 완료 ✅ 이상 감지: {down if down else '없음'}")


scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(monitor_task, "interval", minutes=30)
    scheduler.start()
    asyncio.create_task(monitor_task())
    yield
    scheduler.shutdown()


app = FastAPI(title="서비스 장애 모니터", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(Path("templates/index.html").read_text(encoding="utf-8"))


@app.get("/api/monitor")
async def get_monitor():
    if monitor_cache["results"] is None:
        return JSONResponse({"status": "checking"}, status_code=202)
    return JSONResponse(monitor_cache)


@app.get("/health")
@app.head("/health")
async def health():
    return {"status": "ok"}
