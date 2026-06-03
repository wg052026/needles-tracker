# NEEDLES NEW ARRIVALS TRACKER

KAPITAL 트래커와 동일한 구조로, 아래 3개 사이트의 NEEDLES 신상품을
한 페이지에 모아 보여줍니다. GitHub Actions가 주기적으로 실행되어
`index.html`을 자동 갱신하고 GitHub Pages로 배포됩니다.

| 사이트 | 데이터 소스 | 날짜 기준 |
|--------|-------------|-----------|
| **Nepenthes** | Shopify `products.json` | 사이트 등록일(created) |
| **Studious** | 정적 HTML 파싱 | 트래커 최초 등장일 (이후 고정) |
| **mix.tokyo** | 전체 카탈로그 `products.json` → NEEDLES 필터 | 사이트 등록일(created) |

> Studious는 등록일을 노출하지 않아, KAPITAL 트래커의 Kerouac/S.T.C
> 방식처럼 "트래커가 처음 본 날짜"를 `seen.json`에 고정 저장합니다.

## 동작 방식

- `scrape.py`
  - 세 사이트에서 NEEDLES 상품(이름·가격·이미지·링크·품절여부)을 수집
  - `seen.json`에 최초 등장일/상태를 기록 → 날짜 리셋 방지, 신착 판정
  - 최근 120일 상품을 날짜순으로 정렬해 `index.html` 생성
  - 14일 이내 = `신착` 배지
- `.github/workflows/update.yml`
  - 6시간마다 + 수동 실행 시 `scrape.py`를 돌리고 결과를 커밋

## 처음 한 번만 설정

1. 이 폴더 전체를 새 GitHub 저장소(예: `needles-tracker`)에 푸시
   ```bash
   git init
   git add .
   git commit -m "init needles tracker"
   git branch -M main
   git remote add origin https://github.com/<USERNAME>/needles-tracker.git
   git push -u origin main
   ```
2. 저장소 **Settings → Pages → Build and deployment**
   - Source: **Deploy from a branch**
   - Branch: **main** / **(root)** → Save
3. **Settings → Actions → General → Workflow permissions**
   - **Read and write permissions** 선택 (자동 커밋용)
4. **Actions** 탭에서 `Update NEEDLES Tracker` → **Run workflow**로 첫 실행

배포 후 접속 주소:
`https://<USERNAME>.github.io/needles-tracker/`

## 로컬 테스트

```bash
pip install beautifulsoup4 lxml
python scrape.py
# index.html 을 브라우저로 열기
```

## 조정 가능한 값 (`scrape.py` 상단)

- `NEW_DAYS` — 신착 배지 기간 (기본 14일)
- `WINDOW_DAYS` — 표시 대상 기간 (기본 120일)
