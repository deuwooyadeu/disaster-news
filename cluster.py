#!/usr/bin/env python3
"""
같은 사건을 다룬 기사들을 하나로 묶는다.

filter.py가 만든 data/filtered-latest.json을 읽어
data/events-latest.json과 data/events-{날짜}.json을 만든다.

기사 1,500건을 그대로 넘기면 읽는 쪽에서 감당이 안 되므로,
여기서 사건 단위로 접어 200~400건 규모로 줄인다.
묶는 기준은 제목 어절의 겹침 정도와 지역 일치 여부다.

최종 판단(사건 성격 요약, 종료/진행 여부)은 이 파일을 읽는 쪽이 한다.
여기서는 '같은 사건으로 보이는 기사 묶음'과 언급 횟수만 만든다.

사용:
    python cluster.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SOURCE = DATA_DIR / "filtered-latest.json"

# 제목 어절 자카드 유사도. 실제 7/24 데이터로 0.22~0.34를 시험한 결과
# 0.26이 오병합 없이 쪼개짐이 가장 적었다. 서로 다른 사건을 붙이는 것보다
# 같은 사건을 둘로 나누는 쪽이 안전하므로 일부러 보수적으로 잡았다.
SIM_THRESHOLD = 0.26
MAX_TITLES = 6           # 사건당 남길 제목 수
MAX_SNIPPETS = 3         # 사건당 남길 요약문 수

# 어느 기사에나 나오는 말이라 변별력이 없다.
STOPWORDS = {
    "속보", "종합", "단독", "사고", "발생", "관련", "대한", "위한", "따르면",
    "오전", "오후", "이날", "지난", "현재", "당국", "경찰", "소방", "조사",
    "중이다", "있다", "했다", "밝혔다", "전했다", "위해", "대해", "등이",
    "기자", "사진", "제공", "뉴스", "일보", "방송",
}

TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
NUM_RE = re.compile(r"\d+")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def tokenize(title: str) -> set[str]:
    """제목을 비교용 어절 집합으로 바꾼다."""
    # 말머리 제거
    title = re.sub(r"[\[\(<【].*?[\]\)>】]", " ", title)
    tokens = set()
    for tok in TOKEN_RE.findall(title):
        if tok in STOPWORDS or len(tok) < 2:
            continue
        # 조사 꼬리를 대충 떼어 '보령서'와 '보령에서'를 같게 본다.
        tok = re.sub(r"(에서|에게|으로|이라|라며|까지|부터|에는|서는|은|는|이|가|을|를|의|도|서)$", "", tok)
        if len(tok) >= 2:
            tokens.add(tok)
    return tokens


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def region_key(regions: list[str]) -> set[str]:
    """'평택'과 '평택시'를 같은 지역으로 본다."""
    return {re.sub(r"(시|군|구|도)$", "", r) for r in regions if len(r) >= 2}


class Event:
    __slots__ = ("tokens", "articles", "regions")

    def __init__(self, article: dict, tokens: set[str]):
        self.tokens = set(tokens)
        self.articles = [article]
        self.regions = region_key(article.get("regions", []))

    def add(self, article: dict, tokens: set[str]) -> None:
        # 대표 토큰(self.tokens)은 건드리지 않는다. 기사를 점수순으로 넣기
        # 때문에 첫 기사가 그 사건을 가장 잘 나타내며, 합집합으로 부풀리면
        # 서로 다른 사건까지 빨아들이게 된다.
        self.articles.append(article)
        self.regions |= region_key(article.get("regions", []))

    def similarity(self, tokens: set[str], regions: set[str]) -> float:
        sim = jaccard(self.tokens, tokens)
        # 지역이 겹치면 같은 사건일 가능성이 높아 문턱을 낮춰준다.
        if regions and self.regions and (regions & self.regions):
            sim += 0.12
        return sim


def summarize(event: Event) -> dict:
    arts = sorted(event.articles, key=lambda a: a["pubDate"])

    # 제목은 짧고 정보가 많은 것부터
    titles = []
    seen = set()
    for a in sorted(arts, key=lambda x: -x.get("event_score", 0)):
        t = a["title"]
        norm = re.sub(r"[^가-힣0-9]", "", t)
        if norm in seen:
            continue
        seen.add(norm)
        titles.append(t)
        if len(titles) >= MAX_TITLES:
            break

    snippets = [a["description"] for a in arts if a.get("description")][:MAX_SNIPPETS]

    # 사상자 힌트는 가장 큰 값을 취한다. 후속 보도일수록 숫자가 커지기 때문.
    casualties: dict[str, int] = {}
    for a in arts:
        for k, v in (a.get("casualty_hints") or {}).items():
            casualties[k] = max(casualties.get(k, 0), v)

    regions: dict[str, int] = {}
    for a in arts:
        for r in a.get("regions", []):
            regions[r] = regions.get(r, 0) + 1
    top_regions = [r for r, _ in sorted(regions.items(), key=lambda x: -x[1])[:4]]

    keywords: dict[str, int] = {}
    for a in arts:
        for k in a.get("matched_keywords", []):
            keywords[k] = keywords.get(k, 0) + 1
    top_keywords = [k for k, _ in sorted(keywords.items(), key=lambda x: -x[1])[:6]]

    out = {
        "mention_count": len(arts),
        "titles": titles,
        "snippets": snippets,
        "regions": top_regions,
        "keywords": top_keywords,
        "first_reported": arts[0]["pubDate"],
        "last_reported": arts[-1]["pubDate"],
        "sample_link": arts[0].get("originallink") or arts[0].get("link", ""),
    }
    if casualties:
        out["casualty_hints"] = casualties
    return out


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"선별 파일이 없습니다: {SOURCE}. filter.py를 먼저 실행하세요.")

    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    articles = payload.get("articles", [])
    date_label = payload.get("target_date", "unknown")

    log(f"대상 날짜: {date_label}")
    log(f"입력 {len(articles)}건")

    # 점수 높은 기사가 먼저 와야 대표 제목이 좋게 잡힌다.
    articles = sorted(articles, key=lambda a: (-a.get("event_score", 0), a["pubDate"]))

    events: list[Event] = []
    for art in articles:
        tokens = tokenize(art["title"])
        if not tokens:
            continue
        regions = region_key(art.get("regions", []))

        best: Event | None = None
        best_sim = 0.0
        for ev in events:
            sim = ev.similarity(tokens, regions)
            if sim > best_sim:
                best_sim, best = sim, ev

        if best is not None and best_sim >= SIM_THRESHOLD:
            best.add(art, tokens)
        else:
            events.append(Event(art, tokens))

    summaries = [summarize(ev) for ev in events]
    summaries.sort(key=lambda e: (-e["mention_count"], e["first_reported"]))

    log(f"사건 {len(summaries)}건으로 병합")
    if summaries:
        log("\n상위 10건")
        for e in summaries[:10]:
            log(f"  {e['mention_count']:>3}건  {e['titles'][0][:44]}")

    out = {
        "target_date": date_label,
        "timezone": payload.get("timezone", "Asia/Seoul"),
        "generated_at": payload.get("generated_at"),
        "source_article_count": payload.get("source_article_count"),
        "filtered_article_count": len(articles),
        "event_count": len(summaries),
        "truncated_keywords": payload.get("truncated_keywords", []),
        "events": summaries,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in (DATA_DIR / f"events-{date_label}.json",
                 DATA_DIR / "events-latest.json"):
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"\n저장: events-{date_label}.json, events-latest.json")


if __name__ == "__main__":
    main()
