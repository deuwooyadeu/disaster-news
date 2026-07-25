#!/usr/bin/env python3
"""
수집된 기사에서 '실제 국내 재난·사고 사건'만 남긴다.

collect.py가 만든 data/latest.json을 읽어
data/filtered-latest.json과 data/filtered-{날짜}.json을 만든다.

거르는 방식은 두 단계다.

  1. 제외 — 운세, 날씨 예보, 스포츠·연예·증시 비유, 해외 사건,
            행사·정책·캠페인 기사를 걷어낸다.
  2. 채점 — 남은 기사에 사건성 점수를 매긴다. '숨져', '부상',
            '붕괴' 같은 강한 신호는 2점, '발생', '출동' 같은
            약한 신호는 1점. 합계 2점 이상만 통과시킨다.

통과한 기사에는 추정 지역과 사상자 숫자를 함께 붙여 둔다.
사건 단위 병합과 요약은 여기서 하지 않는다.

사용:
    python filter.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SOURCE = DATA_DIR / "latest.json"

PASS_SCORE = 2          # 이 점수 이상이면 사건으로 본다


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ── 1단계: 제외 규칙 ──────────────────────────────────────────────────

# 네이버 링크의 섹션으로 걸러내는 게 가장 확실하다.
EXCLUDE_URL = re.compile(r"(m\.)?(sports|entertain)\.naver\.com")

# 제목에 이게 있으면 사건 기사가 아니다.
EXCLUDE_TITLE = [
    # 운세·점성
    r"운세", r"별자리", r"띠별", r"사주", r"토정비결",
    # 날씨 예보 정형 기사
    r"오늘.{0,4}날씨", r"내일.{0,4}날씨", r"주간.{0,4}날씨", r"주말.{0,4}날씨",
    r"^\[?날씨", r"날씨\]", r"기상캐스터", r"아침 최저", r"낮 최고",
    # 스포츠
    r"K리그", r"KBO", r"프로야구", r"프로축구", r"월드컵", r"올림픽",
    r"감독", r"선수단", r"구단", r"홈런", r"타율", r"승강전",
    # 증시·경제 비유
    r"증시", r"코스피", r"코스닥", r"주가", r"상장", r"영업익", r"매출",
    r"투자 한파", r"채용 한파", r"수출 한파", r"부동산 한파", r"골 가뭄",
    # 행사·정책·캠페인
    r"캠페인", r"간담회", r"토론회", r"세미나", r"워크숍", r"공모",
    r"기념식", r"발대식", r"출범", r"협약", r"체결", r"위촉", r"임명",
    r"조례", r"추경", r"예산 확보", r"국비 확보", r"의정", r"시의회",
    r"도의회", r"군의회", r"구의회", r"공청회", r"설명회", r"박람회",
    r"교육 실시", r"소양 교육", r"안전교육", r"훈련 실시", r"모의훈련",
    r"점검 나서", r"현장점검", r"안전점검", r"합동점검", r"실태조사",
    r"수상", r"선정", r"표창", r"우수 사례", r"공모전",
    # 칼럼·사설·기획
    r"^\[사설", r"^\[칼럼", r"^\[기고", r"^\[사설\]", r"칼럼\]",
    r"인물탐구", r"연속기획", r"브리핑\]",
    # 법적 절차 — 사건 자체가 아니라 이후 재판 소식
    r"벌금", r"징역", r"구형", r"선고", r"무죄", r"유죄", r"기소",
    r"항소", r"상고", r"재판", r"판결", r"손해배상", r"소송",
]
EXCLUDE_TITLE_RE = re.compile("|".join(EXCLUDE_TITLE))

# 해외 사건 제외. 국내 기사만 본다.
FOREIGN = [
    "미국", "중국", "일본", "러시아", "우크라이나", "이란", "이스라엘",
    "프랑스", "독일", "영국", "스페인", "이탈리아", "그리스", "터키", "튀르키예",
    "인도", "인도네시아", "베트남", "태국", "필리핀", "대만", "홍콩",
    "베네수엘라", "브라질", "멕시코", "페루", "칠레", "아르헨티나",
    "사우디", "예멘", "이라크", "시리아", "아프가니스탄", "파키스탄",
    "호주", "캐나다", "뉴질랜드", "이집트", "나이지리아", "케냐",
    "북한", "평양", "홍해", "가자", "유럽", "아프리카", "중동", "동남아",
    "뉴욕", "워싱턴", "LA", "로스앤젤레스", "런던", "파리", "도쿄", "베이징",
    "실리콘밸리", "샌프란시스코", "할리우드",
]
FOREIGN_RE = re.compile("|".join(FOREIGN))


# ── 2단계: 사건성 채점 ────────────────────────────────────────────────

STRONG = [
    # 인명
    r"숨져", r"숨진", r"숨졌", r"사망", r"목숨을 잃", r"시신",
    r"부상", r"다쳐", r"다친", r"다쳤", r"중상", r"경상", r"화상",
    r"실종", r"고립", r"매몰", r"갇혀", r"갇힌",
    r"구조됐", r"구조했", r"구조 작업", r"심폐소생",
    r"온열질환", r"사상자", r"인명피해",
    r"끼임사", r"끼여", r"깔려", r"추락사", r"질식", r"감전",
    # 물적
    r"전소", r"불에 타", r"붕괴", r"무너져", r"무너진", r"파손",
    r"침수됐", r"침수된", r"물에 잠", r"유실", r"매몰됐",
    r"전복", r"침몰", r"좌초", r"추락했", r"추락한",
    r"폭발", r"누출", r"유출됐",
    # 대응
    r"이재민", r"대피령", r"대피했", r"대피시", r"통제됐", r"긴급 대피",
    r"살처분", r"확진자", r"집단 발병",
]

WEAK = [
    r"발생", r"피해", r"출동", r"신고", r"진화", r"진압", r"수색",
    r"조사 중", r"경위", r"소방", r"경찰", r"당국", r"응급",
    r"사고", r"화재", r"충돌", r"전도", r"낙하",
]

STRONG_RE = re.compile("|".join(STRONG))
WEAK_RE = re.compile("|".join(WEAK))


# ── 부가 정보 추출 ────────────────────────────────────────────────────

REGIONS = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    "수원", "성남", "용인", "고양", "화성", "부천", "안산", "평택", "시흥",
    "김포", "광명", "군포", "하남", "이천", "안성", "의정부", "남양주",
    "춘천", "원주", "강릉", "동해", "삼척", "속초", "태백", "홍천", "평창",
    "청주", "충주", "제천", "천안", "아산", "서산", "당진", "공주", "논산",
    "전주", "익산", "군산", "정읍", "남원", "목포", "여수", "순천", "광양",
    "포항", "경주", "구미", "경산", "안동", "김천", "영주", "상주", "예천",
    "창원", "진주", "김해", "양산", "거제", "통영", "사천", "밀양", "고성",
    "양양", "인제", "횡성", "정선", "영월", "철원", "화천", "양구",
    "홍성", "예산", "보령", "부여", "서천", "금산", "옥천", "영동", "진천",
    "여주", "양평", "가평", "연천", "포천", "파주", "구리", "오산", "과천",
    "나주", "담양", "곡성", "구례", "고흥", "보성", "화순", "장흥", "해남",
    "영암", "무안", "함평", "영광", "장성", "완도", "진도", "신안",
    "영천", "상주", "문경", "의성", "청송", "영양", "영덕", "청도", "고령",
    "성주", "칠곡", "함양", "거창", "합천", "남해", "하동", "산청", "의령",
    "서귀포",
]
# 위 목록에 없는 지자체도 잡기 위한 보조 패턴 (예: 부천시, 강서구, 울주군)
# 앞뒤가 한글이면 제외한다. '낚시도구', '가재도구' 같은 오탐을 막기 위함.
REGION_GENERIC = re.compile(r"(?<![가-힣])[가-힣]{2}(?:시|군|구)(?![가-힣])")
REGION_RE = re.compile("|".join(REGIONS))

CASUALTY_PATTERNS = [
    ("dead", re.compile(r"(\d+)\s*명(?:이|은|도)?\s*(?:숨지|숨져|숨졌|사망)")),
    ("injured", re.compile(r"(\d+)\s*명(?:이|은|도)?\s*(?:부상|다쳐|다쳤|중상|경상)")),
    ("missing", re.compile(r"(\d+)\s*명(?:이|은|도)?\s*(?:실종|고립|매몰)")),
    ("evacuated", re.compile(r"(\d+)(?:여)?\s*명(?:이|은|도)?\s*(?:대피|피신)")),
]


def extract_casualties(text: str) -> dict:
    found = {}
    for label, pattern in CASUALTY_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                found[label] = int(m.group(1))
            except ValueError:
                pass
    return found


def extract_regions(text: str) -> list[str]:
    found = set(REGION_RE.findall(text))
    found.update(REGION_GENERIC.findall(text))
    return sorted(found)


def has_region(text: str) -> bool:
    return bool(REGION_RE.search(text) or REGION_GENERIC.search(text))


# ── 판정 ──────────────────────────────────────────────────────────────

def judge(article: dict) -> tuple[bool, int, str]:
    """(통과 여부, 점수, 탈락 사유)를 반환한다."""
    title = article.get("title", "")
    desc = article.get("description", "")
    link = (article.get("link", "") or "") + " " + (article.get("originallink", "") or "")
    blob = f"{title} {desc}"

    if EXCLUDE_URL.search(link):
        return False, 0, "스포츠/연예 섹션"
    if EXCLUDE_TITLE_RE.search(title):
        return False, 0, "제외 주제"
    if FOREIGN_RE.search(title):
        return False, 0, "해외 사건"

    score = 0
    # 제목에 있는 신호는 더 크게 본다.
    if STRONG_RE.search(title):
        score += 3
    elif STRONG_RE.search(desc):
        score += 2
    if WEAK_RE.search(title):
        score += 1
    elif WEAK_RE.search(desc):
        score += 1

    # 국내 지명이 있으면 실제 사건일 가능성이 높다.
    if has_region(title):
        score += 1

    if score < PASS_SCORE:
        return False, score, "사건성 부족"
    return True, score, ""


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"수집 파일이 없습니다: {SOURCE}. collect.py를 먼저 실행하세요.")

    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    articles = payload.get("articles", [])
    date_label = payload.get("target_date", "unknown")

    log(f"대상 날짜: {date_label}")
    log(f"입력 {len(articles)}건\n")

    kept: list[dict] = []
    reasons: dict[str, int] = {}

    for art in articles:
        ok, score, reason = judge(art)
        if not ok:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue

        blob = f"{art.get('title', '')} {art.get('description', '')}"
        record = dict(art)
        record["event_score"] = score
        record["regions"] = extract_regions(blob)
        casualties = extract_casualties(blob)
        if casualties:
            record["casualty_hints"] = casualties
        kept.append(record)

    # 점수 높은 순 → 시간 순
    kept.sort(key=lambda r: (-r["event_score"], r["pubDate"]))

    log("탈락 내역")
    for reason, n in sorted(reasons.items(), key=lambda x: -x[1]):
        log(f"  {reason:<16} {n:>5}건")
    log(f"\n통과 {len(kept)}건 ({len(kept) / max(len(articles), 1) * 100:.1f}%)")

    out = {
        "target_date": date_label,
        "timezone": payload.get("timezone", "Asia/Seoul"),
        "generated_at": payload.get("generated_at"),
        "source_article_count": len(articles),
        "filtered_article_count": len(kept),
        "dropped_by_reason": reasons,
        "truncated_keywords": payload.get("truncated_keywords", []),
        "articles": kept,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in (DATA_DIR / f"filtered-{date_label}.json",
                 DATA_DIR / "filtered-latest.json"):
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"저장: filtered-{date_label}.json, filtered-latest.json")


if __name__ == "__main__":
    main()
