#!/usr/bin/env python3
"""
전날(KST) 국내 재난·사고 뉴스 수집기

네이버 검색 API(뉴스)를 키워드별로 호출해 전날 보도된 기사를 모으고,
중복을 제거한 뒤 JSON으로 저장한다. 사건 병합·랭킹·요약은 하지 않는다.
그건 이 파일을 읽는 쪽(Cowork 예약 작업)이 담당한다.

환경변수:
    NAVER_CLIENT_ID      네이버 개발자센터 애플리케이션 Client ID
    NAVER_CLIENT_SECRET  같은 애플리케이션의 Client Secret
    TARGET_DATE          (선택) 수집 대상 날짜. YYYY-MM-DD. 미지정 시 어제(KST).

사용:
    python collect.py
    TARGET_DATE=2026-07-24 python collect.py
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────────────

API_URL = "https://openapi.naver.com/v1/search/news.json"

KST = timezone(timedelta(hours=9))

# 네이버 검색 API 제약: display 최대 100, start 최대 1000,
# 그리고 start + display - 1 <= 1000 이어야 한다.
DISPLAY = 100
MAX_START = 901          # 901 + 100 - 1 = 1000
PAGE_STARTS = list(range(1, MAX_START + 1, DISPLAY))   # 1, 101, ..., 901

REQUEST_PAUSE = 0.12     # 초. 호출 간 간격
MAX_RETRIES = 3

ROOT = Path(__file__).resolve().parent
KEYWORD_FILE = ROOT / "keywords.txt"
OUTPUT_DIR = ROOT / "data"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


# ── 유틸 ──────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def clean(text: str) -> str:
    """네이버가 돌려주는 <b> 태그와 HTML 엔티티를 제거한다."""
    text = TAG_RE.sub("", text or "")
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


def load_keywords(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"키워드 파일이 없습니다: {path}")
    seen: set[str] = set()
    keywords: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line not in seen:
            seen.add(line)
            keywords.append(line)
    if not keywords:
        raise SystemExit("키워드 파일에 유효한 키워드가 없습니다.")
    return keywords


def target_date() -> datetime:
    """수집 대상 날짜(KST 자정)를 반환한다."""
    explicit = os.environ.get("TARGET_DATE", "").strip()
    if explicit:
        try:
            d = datetime.strptime(explicit, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(f"TARGET_DATE 형식이 잘못됐습니다: {explicit} (YYYY-MM-DD)")
        return d.replace(tzinfo=KST)
    now_kst = datetime.now(KST)
    yesterday = now_kst - timedelta(days=1)
    return yesterday.replace(hour=0, minute=0, second=0, microsecond=0)


def normalize_title(title: str) -> str:
    """중복 판정용 제목 정규화. 문장부호·공백·괄호 내용을 걷어낸다."""
    t = unicodedata.normalize("NFKC", title)
    t = re.sub(r"[\[\(<【].*?[\]\)>】]", " ", t)     # [단독] (종합) 등 말머리 제거
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", t)
    return t.lower()


# ── API 호출 ──────────────────────────────────────────────────────────

def fetch_page(query: str, start: int, client_id: str, client_secret: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "query": query,
        "display": DISPLAY,
        "start": start,
        "sort": "date",       # 최신순. 날짜 경계로 조기 종료하려면 필수.
    })
    req = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("items", [])
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            # 400은 start 범위 초과 등 재시도해도 소용없는 경우가 많다.
            if e.code == 400:
                log(f"    [{query}] start={start} 400: {body}")
                return []
            if e.code == 429 or e.code >= 500:
                wait = 2 ** attempt
                log(f"    [{query}] start={start} HTTP {e.code}, {wait}초 후 재시도")
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                raise SystemExit(f"인증 실패(HTTP {e.code}). API 키를 확인하세요. {body}")
            log(f"    [{query}] start={start} HTTP {e.code}: {body}")
            return []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            wait = 2 ** attempt
            log(f"    [{query}] start={start} {type(e).__name__}, {wait}초 후 재시도")
            time.sleep(wait)

    log(f"    [{query}] start={start} 재시도 소진, 건너뜀")
    return []


def collect_keyword(
    keyword: str,
    day_start: datetime,
    day_end: datetime,
    client_id: str,
    client_secret: str,
) -> tuple[list[dict], bool]:
    """
    한 키워드에 대해 대상 날짜의 기사를 모은다.

    반환값의 두 번째 요소는 '창 소진 여부'다. 1,000건 창을 다 쓰고도
    대상 날짜 이전으로 내려가지 못했다면 True. 그 키워드는 결과가
    잘렸을 수 있다는 뜻이라 리포트에 남긴다.
    """
    collected: list[dict] = []
    exhausted = False

    for start in PAGE_STARTS:
        items = fetch_page(keyword, start, client_id, client_secret)
        time.sleep(REQUEST_PAUSE)

        if not items:
            break

        passed_window = False
        for item in items:
            raw_date = item.get("pubDate", "")
            try:
                pub = parsedate_to_datetime(raw_date).astimezone(KST)
            except (TypeError, ValueError):
                continue

            if pub >= day_end:
                continue          # 대상 날짜보다 최신 → 아직 도달 전
            if pub < day_start:
                passed_window = True   # 대상 날짜보다 과거 → 지나침
                continue

            collected.append({
                "title": clean(item.get("title", "")),
                "description": clean(item.get("description", "")),
                "link": item.get("link", ""),
                "originallink": item.get("originallink", ""),
                "pubDate": pub.isoformat(),
                "keyword": keyword,
            })

        if passed_window:
            break                 # 정렬이 최신순이므로 더 볼 필요 없음
        if len(items) < DISPLAY:
            break                 # 결과 소진
        if start == PAGE_STARTS[-1]:
            exhausted = True      # 창을 다 쓰고도 못 내려감

    return collected, exhausted


# ── 중복 제거 ─────────────────────────────────────────────────────────

def dedupe(articles: list[dict]) -> list[dict]:
    """
    같은 기사를 한 건으로 합친다. 여러 키워드에 동시에 걸린 기사는
    matched_keywords에 모아둔다. 사건 단위 병합이 아니라 기사 단위 병합이다.
    """
    merged: dict[str, dict] = {}

    for art in articles:
        key = art["originallink"].strip() or art["link"].strip()
        if not key:
            key = "title:" + normalize_title(art["title"])

        if key in merged:
            kws = merged[key]["matched_keywords"]
            if art["keyword"] not in kws:
                kws.append(art["keyword"])
            continue

        record = {k: v for k, v in art.items() if k != "keyword"}
        record["matched_keywords"] = [art["keyword"]]
        merged[key] = record

    # 링크가 달라도 제목이 사실상 같으면 같은 기사로 본다.
    by_title: dict[str, dict] = {}
    for record in merged.values():
        tkey = normalize_title(record["title"])
        if not tkey:
            by_title[record["link"] or record["title"]] = record
            continue
        if tkey in by_title:
            existing = by_title[tkey]
            for kw in record["matched_keywords"]:
                if kw not in existing["matched_keywords"]:
                    existing["matched_keywords"].append(kw)
        else:
            by_title[tkey] = record

    result = list(by_title.values())
    result.sort(key=lambda r: r["pubDate"])
    return result


# ── 메인 ──────────────────────────────────────────────────────────────

def main() -> None:
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 필요합니다.")

    day_start = target_date()
    day_end = day_start + timedelta(days=1)
    date_label = day_start.strftime("%Y-%m-%d")

    keywords = load_keywords(KEYWORD_FILE)
    log(f"대상 날짜: {date_label} (KST)")
    log(f"키워드 {len(keywords)}개\n")

    all_articles: list[dict] = []
    truncated: list[str] = []
    per_keyword: dict[str, int] = {}

    for i, kw in enumerate(keywords, 1):
        got, exhausted = collect_keyword(kw, day_start, day_end, client_id, client_secret)
        all_articles.extend(got)
        per_keyword[kw] = len(got)
        if exhausted:
            truncated.append(kw)
        log(f"  [{i:>3}/{len(keywords)}] {kw:<20} {len(got):>4}건"
            + ("  ⚠ 창 소진" if exhausted else ""))

    articles = dedupe(all_articles)

    log(f"\n수집 {len(all_articles)}건 → 중복 제거 후 {len(articles)}건")
    if truncated:
        log(f"⚠ 1,000건 창을 소진한 키워드: {', '.join(truncated)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_date": date_label,
        "timezone": "Asia/Seoul",
        "generated_at": datetime.now(KST).isoformat(),
        "keyword_count": len(keywords),
        "raw_hits": len(all_articles),
        "article_count": len(articles),
        "truncated_keywords": truncated,
        "hits_per_keyword": per_keyword,
        "articles": articles,
    }

    dated = OUTPUT_DIR / f"{date_label}.json"
    latest = OUTPUT_DIR / "latest.json"
    for path in (dated, latest):
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    log(f"저장: {dated.name}, {latest.name}")


if __name__ == "__main__":
    main()
