# 재난·사고 뉴스 일일 수집기

전날(KST) 국내에서 보도된 재난·사고 기사를 네이버 검색 API로 모아
GitHub 저장소에 JSON으로 쌓는다. 사건 병합·순위·요약은 Cowork 예약 작업이
이 JSON을 읽어서 처리한다.

수집(GitHub Actions)과 분석(Cowork)을 나눈 이유는 하나다.
Cowork 실행 환경에서는 외부 API를 직접 호출할 수 없다.
GitHub 러너는 제약이 없으므로 거기서 받아오고, 결과만 넘긴다.

```
GitHub Actions (매일 06:00 KST)
   └─ 네이버 뉴스 API 호출 → data/latest.json 커밋
        └─ Cowork 예약 작업이 raw URL로 읽어 사건 병합·랭킹·요약
```

---

## 1. 네이버 API 키 발급

1. <https://developers.naver.com/apps/#/register> 접속 (네이버 로그인 필요)
2. **애플리케이션 이름**: 아무거나 (예: `disaster-news`)
3. **사용 API**: `검색` 선택
4. **비로그인 오픈 API 서비스 환경**: `WEB 설정` 선택 후 URL은
   `http://localhost` 입력 (검색 API는 실제로 이 값을 쓰지 않는다)
5. 등록하면 **Client ID**와 **Client Secret**이 나온다. 둘 다 복사해둔다.

무료이고 승인 대기가 없다. 하루 25,000회까지 호출할 수 있는데,
이 스크립트는 키워드 60여 개 기준 하루 100~600회 정도만 쓴다.

## 2. 저장소 만들기

GitHub에서 새 저장소를 만든다. **Public**을 권장한다.
Private도 되지만 Actions 실행 시간이 월 2,000분으로 제한된다
(이 작업은 하루 1~2분이라 사실 어느 쪽이든 여유롭다).

파일을 아래 구조로 넣는다.

```
저장소 루트/
├── collect.py
├── keywords.txt
├── README.md
└── .github/
    └── workflows/
        └── daily-collect.yml
```

`daily-collect.yml`은 반드시 `.github/workflows/` 아래에 있어야 한다.
`data/` 폴더는 스크립트가 알아서 만든다.

## 3. 시크릿 등록

저장소 → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**에서 두 개를 등록한다.

| 이름 | 값 |
|---|---|
| `NAVER_CLIENT_ID` | 1단계에서 받은 Client ID |
| `NAVER_CLIENT_SECRET` | 1단계에서 받은 Client Secret |

키를 `collect.py`나 워크플로 파일에 직접 적지 않는다.
공개 저장소라면 그대로 노출된다.

## 4. 첫 실행

저장소 → **Actions** 탭 → 왼쪽에서 **재난뉴스 일일 수집** 선택 →
오른쪽 **Run workflow** 버튼. 날짜를 비워두면 어제 기준으로 돈다.

몇 분 뒤 `data/latest.json`과 `data/YYYY-MM-DD.json`이 커밋된다.
실패하면 실행 로그에 키워드별 수집 건수와 오류가 찍혀 있다.

## 5. Cowork에 연결

`data/latest.json`의 raw URL을 Claude에게 알려주면 된다. 형식은 이렇다.

```
https://raw.githubusercontent.com/<사용자명>/<저장소명>/main/data/latest.json
```

브라우저에서 열어 JSON이 보이는지 먼저 확인한다.
그다음 Claude에게 이 URL을 주고 예약 작업을 만들어 달라고 하면 된다.

---

## 동작 방식

**날짜 처리** — 네이버 검색 API에는 기간 필터가 없다. 대신 최신순(`sort=date`)으로
받아 내려가다가 대상 날짜보다 과거 기사가 나오면 그 키워드는 즉시 중단한다.
불필요한 호출이 없다.

**수집 범위** — 키워드 하나당 최대 1,000건까지만 조회할 수 있다(네이버 제약).
1,000건을 다 쓰고도 전날까지 못 내려간 키워드는 결과 JSON의
`truncated_keywords`에 기록된다. 이 목록이 비어 있지 않다면 그 키워드를
더 좁은 표현으로 쪼개는 게 좋다. 예: `화재` → `아파트화재`, `공장화재`, `산불`.

**중복 제거** — 원문 링크가 같으면 한 건으로 합친다. 링크가 달라도
말머리(`[속보]`, `(종합)` 등)와 문장부호를 걷어낸 제목이 같으면 역시 합친다.
여러 키워드에 동시에 걸린 기사는 `matched_keywords`에 전부 남는다.

이건 **기사 단위** 병합이지 **사건 단위** 병합이 아니다.
"같은 사건을 다룬 서로 다른 기사 200건을 1개 사건으로" 묶는 작업은
Cowork 쪽에서 제목·본문 요약을 읽고 판단한다.

## 결과 JSON 구조

```jsonc
{
  "target_date": "2026-07-24",
  "timezone": "Asia/Seoul",
  "generated_at": "2026-07-25T06:03:11+09:00",
  "keyword_count": 63,
  "raw_hits": 2841,          // 중복 포함 총 수집량
  "article_count": 1607,     // 중복 제거 후
  "truncated_keywords": [],  // 1,000건 창을 소진한 키워드
  "hits_per_keyword": { "화재": 412, "교통사고": 380, ... },
  "articles": [
    {
      "title": "경산 아파트 관리사무소 방화 피해자 사망",
      "description": "경북 경산시의 한 아파트 관리사무소에서 발생한...",
      "link": "https://n.news.naver.com/...",
      "originallink": "https://www.hankookilbo.com/...",
      "pubDate": "2026-07-24T16:11:09+09:00",
      "matched_keywords": ["화재", "인명피해", "소방당국"]
    }
  ]
}
```

## 키워드 조정

`keywords.txt`를 고치고 커밋하면 다음 실행부터 반영된다.
`#`으로 시작하는 줄과 빈 줄은 무시되므로 주석과 분류 제목을 자유롭게 쓸 수 있다.

며칠 돌려보고 `hits_per_keyword`를 확인하는 걸 권한다.
0건에 가까운 키워드는 빼고, 노이즈가 많은 키워드는 더 구체적으로 바꾼다.

## 알아둘 것

- **예약 실행 지연** — GitHub Actions의 cron은 혼잡 시간대에 수 분에서
  십수 분 늦게 시작될 수 있다. 정시 보장은 없다.
- **공개 저장소 60일 규칙** — 공개 저장소에 60일간 활동이 없으면
  예약 워크플로가 자동으로 비활성화된다. 이 워크플로는 매일 결과를
  커밋하므로 해당되지 않는다.
- **커버리지** — 네이버 검색 색인 기반이라 "국내 모든 기사"를 보장하지 않는다.
  진짜 전수가 필요하면 한국언론진흥재단 빅카인즈 OPEN API 승인을 받아
  `collect.py`의 호출 부분만 교체하면 된다. 나머지 구조는 그대로 쓸 수 있다.
- **본문 없음** — 네이버 검색 API는 제목과 짧은 요약만 준다.
  사망자 수나 재산피해 같은 수치는 여러 기사의 요약을 종합해 추정한다.
  더 정확한 수치가 필요하면 상위 사건에 한해 원문을 긁는 단계를 추가할 수 있다.
