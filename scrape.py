#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEEDLES NEW ARRIVALS TRACKER
- Nepenthes (Shopify products.json)  -> created_at 기준
- Studious (FUTURESHOP static HTML)  -> 최초 등장일 고정
- mix.tokyo (Shopify search)         -> 최초 등장일 고정

KAPITAL TRACKER 와 동일 구조:
- seen.json 에 최초 등장일/상태 저장 (리셋 방지, 신착 판정)
- GitHub Actions 가 주기적으로 실행, index.html 갱신
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from html import escape

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
SEEN_PATH = os.path.join(os.path.dirname(__file__), "seen.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "index.html")
NEW_DAYS = 14          # "신착" 표시 기간
WINDOW_DAYS = 120      # 표시 대상 기간
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            with open(SEEN_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_seen(seen):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# 1) NEPENTHES  (Shopify) — created_at 사용 가능
# ---------------------------------------------------------------------------
def scrape_nepenthes():
    out = []
    base = ("https://onlinestore.nepenthes.co.jp/collections/needles/"
            "products.json?limit=250&page=%d")
    for page in range(1, 6):
        try:
            data = json.loads(fetch(base % page))
        except Exception as e:
            print(f"[nepenthes] page {page} error: {e}", file=sys.stderr)
            break
        prods = data.get("products", [])
        if not prods:
            break
        for p in prods:
            handle = p.get("handle", "")
            url = f"https://onlinestore.nepenthes.co.jp/products/{handle}"
            title = p.get("title", "").strip()
            variants = p.get("variants", [])
            price = ""
            available = False
            if variants:
                price = variants[0].get("price", "")
                available = any(v.get("available") for v in variants)
            colors = shopify_colors(variants)
            img = ""
            if p.get("images"):
                img = p["images"][0].get("src", "")
            created = p.get("created_at") or p.get("published_at") or ""
            out.append({
                "id": f"nep-{p.get('id')}",
                "title": title,
                "price_yen": _yen(price),
                "url": url,
                "img": img,
                "created": created[:10] if created else "",
                "soldout": not available,
                "colors": colors,
            })
        if len(prods) < 250:
            break
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------------------
# 2) STUDIOUS  (FUTURESHOP static HTML) — created date 없음 -> 최초 등장 고정
# ---------------------------------------------------------------------------
def scrape_studious():
    if BeautifulSoup is None:
        return []
    out = []
    url = "https://studious.co.jp/shop/NEEDLES/r/rnds/"
    try:
        html = fetch(url)
    except Exception as e:
        print(f"[studious] error: {e}", file=sys.stderr)
        return out
    soup = BeautifulSoup(html, "lxml")
    items = soup.select("li .block-goods-list-d--item-body")
    grouped = {}
    order = []
    for it in items:
        a = it.select_one('a[href*="/shop/g/g"]')
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"/shop/g/(g\d+)/", href)
        if not m:
            continue
        link = "https://studious.co.jp" + href
        name_el = it.select_one(".js-enhanced-ecommerce-goods-name-2")
        title = name_el.get_text(strip=True) if name_el else a.get("title", "")
        price_el = it.select_one(".block-goods-list-d--price")
        price = price_el.get_text(strip=True) if price_el else ""
        img_el = it.select_one("img")
        img = ""
        if img_el and img_el.get("src"):
            src = img_el["src"]
            img = src if src.startswith("http") else "https://studious.co.jp" + src
        key = title.strip()
        if not key:
            continue
        if key not in grouped:
            grouped[key] = {
                "id": "stu-" + m.group(1),
                "title": title,
                "price_yen": _yen(price),
                "url": link,
                "img": img,
                "created": "",      # 노출 없음 -> seen.json 최초 등장일 사용
                "soldout": False,
                # 목록에 색상별 재고가 없어 상태 미상(None)으로 표시
                "colors": [],
                "_variant_ids": set(),
            }
            order.append(key)
        g = grouped[key]
        g["_variant_ids"].add(m.group(1))
        if not g["img"] and img:
            g["img"] = img
    for key in order:
        g = grouped[key]
        n = len(g["_variant_ids"])
        # 색상 가짓수만큼 상태 미상 점 (available=None)
        g["colors"] = [{"name": "", "available": None} for _ in range(min(n, 8))]
        del g["_variant_ids"]
        out.append(g)
    return out


# ---------------------------------------------------------------------------
# 3) MIX.TOKYO  (Shopify search) — created date 없음 -> 최초 등장 고정
# ---------------------------------------------------------------------------
def scrape_mix():
    """mix.tokyo는 검색이 JS 렌더라 정적 파싱 불가.
    전체 카탈로그(products.json 페이지네이션)를 받아 NEEDLES만 필터링한다.
    Shopify products.json 은 created_at 을 제공하므로 날짜 정렬도 가능."""
    out = []
    seen_ids = set()
    for page in range(1, 45):
        url = f"https://mix.tokyo/products.json?limit=250&page={page}"
        try:
            data = json.loads(fetch(url))
        except Exception as e:
            print(f"[mix] page {page} error: {e}", file=sys.stderr)
            break
        prods = data.get("products", [])
        if not prods:
            break
        for p in prods:
            pid = p.get("id")
            if pid in seen_ids:
                continue
            vendor = (p.get("vendor") or "")
            title = (p.get("title") or "")
            tags = p.get("tags", [])
            tagstr = " ".join(tags) if isinstance(tags, list) else str(tags)
            ptype = (p.get("product_type") or "")
            blob = f"{vendor} {tagstr} {ptype} {title}".lower()
            if "needles" not in blob and "ニードルズ" not in title:
                continue
            seen_ids.add(pid)
            handle = p.get("handle", "")
            link = f"https://mix.tokyo/products/{handle}"
            price = ""
            available = True
            variants = p.get("variants", [])
            if variants:
                price = variants[0].get("price", "")
                available = any(v.get("available") for v in variants)
            colors = shopify_colors(variants)
            img = ""
            imgs = p.get("images") or []
            if imgs:
                first = imgs[0]
                img = first.get("src") if isinstance(first, dict) else first
            created = p.get("created_at") or p.get("published_at") or ""
            out.append({
                "id": f"mix-{pid}",
                "title": title.strip(),
                "price_yen": _yen(str(price)),
                "url": link,
                "img": img,
                "created": created[:10] if created else "",
                "soldout": not available,
                "colors": colors,
            })
        if len(prods) < 250:
            break
        time.sleep(0.3)
    return out


def shopify_colors(variants):
    """variant 목록에서 색상(option1)별 재고 상태를 집계.
    같은 색상의 사이즈 중 하나라도 available 이면 그 색상은 재고 있음.
    반환: [{"name": 색상, "available": bool}, ...] (입력 순서 유지)"""
    order = []
    state = {}
    for v in variants:
        color = v.get("option1") or "—"
        if color not in state:
            state[color] = False
            order.append(color)
        if v.get("available"):
            state[color] = True
    return [{"name": c, "available": state[c]} for c in order]


def _yen(v):
    if v is None:
        return ""
    s = str(v)
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return ""
    try:
        return "¥{:,}".format(int(digits))
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# 신착/날짜 판정 + seen.json 갱신
# ---------------------------------------------------------------------------
def reconcile(shop, items, seen):
    """각 상품에 표시용 날짜(date)와 is_new 부여. seen.json 갱신."""
    shop_seen = seen.setdefault(shop, {})
    today = NOW.strftime("%Y-%m-%d")
    result = []
    for it in items:
        sid = it["id"]
        rec = shop_seen.get(sid)
        # 사이트가 created 를 주면 그걸 우선, 아니면 최초 관측일 고정
        if it.get("created"):
            disp_date = it["created"]
        elif rec and rec.get("first"):
            disp_date = rec["first"]
        else:
            disp_date = today
        if not rec:
            shop_seen[sid] = {"first": disp_date, "title": it["title"]}
        else:
            rec["title"] = it["title"]
            if not rec.get("first"):
                rec["first"] = disp_date
        it["date"] = disp_date
        result.append(it)
    return result


def within_window(it):
    d = it.get("date", "")
    try:
        dt = datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=KST)
    except Exception:
        return True
    return (NOW - dt).days <= WINDOW_DAYS


def is_new(it):
    d = it.get("date", "")
    try:
        dt = datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=KST)
    except Exception:
        return False
    return (NOW - dt).days <= NEW_DAYS


def sort_key(it):
    return (it.get("date", ""), it.get("id", ""))


# ---------------------------------------------------------------------------
# HTML 빌드 (KAPITAL TRACKER 스타일)
# ---------------------------------------------------------------------------
def kream(title):
    # 상품 코드 추정: 영숫자-하이픈 토큰
    return None


def color_dots_html(it):
    """색상별 재고 점. available True=재고(초록), False=품절(빨강),
    None=상태미상(회색). 점 위에 색상명 툴팁."""
    colors = it.get("colors") or []
    if not colors:
        return ""
    dots = []
    for c in colors:
        av = c.get("available")
        cls = "dot-ok" if av is True else ("dot-sold" if av is False else "dot-unknown")
        name = escape(c.get("name") or "")
        title_attr = f' title="{name}"' if name else ""
        dots.append(f'<span class="dot {cls}"{title_attr}></span>')
    return '<div class="dots">' + "".join(dots) + '</div>'


def build_html(sections):
    cols = []
    grand_total = 0
    for shop_name, shop_url, items in sections:
        items = [i for i in items if within_window(i)]
        items.sort(key=sort_key, reverse=True)
        grand_total += len(items)
        head = (f'<div class="shop-head">'
                f'<span class="shop-name">{escape(shop_name)}</span>'
                f'<span class="shop-count">{len(items)}</span>'
                f'<a class="shop-link" href="{escape(shop_url)}" '
                f'target="_blank" rel="noopener">↗</a></div>')
        rows = []
        if not items:
            rows.append('<div class="empty">-</div>')
        for it in items:
            new_badge = '<span class="badge-new">신착</span>' if is_new(it) else ''
            allsold = it.get("soldout")
            sold_band = '<div class="sold-band">SOLD OUT</div>' if allsold else ''
            img = it.get("img") or ""
            inner = f'{color_dots_html(it)}{sold_band}'
            imgtag = (f'<div class="thumb"><img loading="lazy" src="{escape(img)}" '
                      f'alt="">{inner}</div>'
                      if img else
                      f'<div class="thumb noimg">{inner}</div>')
            price = escape(it.get("price_yen") or "")
            rows.append(
                f'<a class="card{" is-sold" if allsold else ""}" '
                f'href="{escape(it["url"])}" target="_blank" rel="noopener">'
                f'{imgtag}'
                f'<div class="meta">'
                f'<div class="title">{escape(it["title"])}</div>'
                f'<div class="row"><span class="price">{price}</span>'
                f'<span class="date">{escape(it.get("date",""))}</span></div>'
                f'<div class="badges">{new_badge}</div>'
                f'</div></a>'
            )
        cols.append(f'<div class="col">{head}'
                    f'<div class="col-body">{"".join(rows)}</div></div>')

    body = '<div class="board">' + "".join(cols) + '</div>'
    updated = NOW.strftime("%Y.%m.%d %H:%M KST")
    return TEMPLATE.format(
        updated=updated, total=grand_total, window=WINDOW_DAYS,
        new_days=NEW_DAYS, body=body,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEEDLES NEW ARRIVALS TRACKER</title>
<style>
:root{{--bg:#0f0f10;--card:#19191b;--line:#2a2a2d;--fg:#f2f2f2;--mut:#8b8b90;--accent:#e7402b;}}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;}}
header{{padding:24px 16px 10px;border-bottom:1px solid var(--line);}}
h1{{font-size:20px;letter-spacing:.04em;margin:0 0 6px;}}
.sub{{color:var(--mut);font-size:13px;line-height:1.6;}}
.legend{{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:12px;color:var(--mut);align-items:center;}}
.legend .dot{{position:static;margin-right:4px;}}
main{{padding:0;}}
/* 사이트별 컬럼을 가로로 나열, 컬럼 안은 2열 그리드 */
.board{{display:flex;gap:0;overflow-x:auto;align-items:flex-start;
padding:0 0 40px;-webkit-overflow-scrolling:touch;}}
.col{{flex:0 0 380px;min-width:380px;border-right:1px solid var(--line);}}
.col-body{{padding:10px;display:grid;grid-template-columns:1fr 1fr;
gap:12px;align-content:start;}}
.empty{{grid-column:1 / -1;}}
.shop-head{{position:sticky;top:0;z-index:2;background:var(--bg);
display:flex;align-items:center;gap:8px;padding:14px 12px 10px;
border-bottom:1px solid var(--line);}}
.shop-name{{font-weight:700;font-size:14px;letter-spacing:.04em;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.shop-count{{color:var(--mut);font-size:11px;}}
.shop-link{{margin-left:auto;color:var(--mut);font-size:13px;text-decoration:none;}}
.shop-link:hover{{color:var(--fg);}}
.card{{display:flex;flex-direction:column;background:var(--card);
border:1px solid var(--line);border-radius:9px;overflow:hidden;
text-decoration:none;color:inherit;margin:0;transition:border-color .15s;}}
.card:hover{{border-color:var(--accent);}}
.card.is-sold .thumb img{{filter:grayscale(.7) brightness(.7);}}
.thumb{{position:relative;aspect-ratio:3/4;background:#101012;overflow:hidden;}}
.thumb img{{width:100%;height:100%;object-fit:cover;display:block;}}
.thumb.noimg{{display:flex;align-items:center;justify-content:center;color:#3a3a3d;}}
/* 색상별 재고 점 */
.dots{{position:absolute;top:6px;left:6px;display:flex;gap:4px;flex-wrap:wrap;
max-width:80%;}}
.dot{{width:9px;height:9px;border-radius:50%;display:inline-block;
box-shadow:0 0 0 1.5px rgba(0,0,0,.55);}}
.dot-ok{{background:#37d36b;}}
.dot-sold{{background:#e7402b;}}
.dot-unknown{{background:#9a9aa0;}}
/* 품절 가로 띠 (KAPITAL 스타일) */
.sold-band{{position:absolute;top:50%;left:0;right:0;transform:translateY(-50%);
background:rgba(20,20,22,.82);color:#e7402b;text-align:center;
font-weight:800;font-size:13px;letter-spacing:.12em;padding:7px 0;
border-top:1px solid rgba(231,64,43,.5);border-bottom:1px solid rgba(231,64,43,.5);}}
.meta{{padding:7px 8px 9px;display:flex;flex-direction:column;gap:4px;flex:1;}}
.title{{font-size:11.5px;line-height:1.35;height:3.1em;overflow:hidden;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}}
.row{{display:flex;justify-content:space-between;align-items:baseline;
gap:6px;margin-top:auto;}}
.price{{font-size:12.5px;font-weight:600;}}
.date{{font-size:10.5px;color:var(--mut);white-space:nowrap;}}
.badges{{display:flex;gap:4px;min-height:14px;}}
.badge-new{{background:var(--accent);color:#fff;font-size:9.5px;
padding:1px 5px;border-radius:4px;font-weight:700;}}
.badge-sold{{background:#3a3a3d;color:#bbb;font-size:9.5px;
padding:1px 5px;border-radius:4px;}}
.empty{{color:var(--mut);padding:14px 0;grid-column:1 / -1;}}
footer{{border-top:1px solid var(--line);padding:16px;color:var(--mut);
font-size:12px;text-align:center;}}
</style>
</head>
<body>
<header>
<h1>NEEDLES NEW ARRIVALS TRACKER</h1>
<div class="sub">업데이트: {updated}<br>
총 {total}개 표시 중 (최근 {window}일 · {new_days}일 이내 신착 표시)</div>
<div class="legend">
<span><span class="dot dot-ok"></span>재고</span>
<span><span class="dot dot-sold"></span>품절</span>
<span><span class="dot dot-unknown"></span>상태 미상</span>
<span style="color:#6a6a70">· 점 = 색상별 재고 상태</span>
</div>
</header>
<main>
{body}
</main>
<footer>
※ Nepenthes · mix.tokyo: 사이트 등록일(created) 기준<br>
※ Studious: 트래커 최초 등장일 기준 (이후 고정)<br>
NEEDLES TRACKER · GitHub Actions 자동 업데이트
</footer>
</body>
</html>
"""

# urllib.parse 는 mix 에서 필요
import urllib.parse  # noqa: E402


def main():
    seen = load_seen()

    sources = [
        ("NEPENTHES", "https://onlinestore.nepenthes.co.jp/collections/needles",
         scrape_nepenthes),
        ("STUDIOUS", "https://studious.co.jp/shop/NEEDLES/r/rnds/",
         scrape_studious),
        ("MIX.TOKYO", "https://mix.tokyo/search?q=needles",
         scrape_mix),
    ]

    sections = []
    for name, url, fn in sources:
        try:
            items = fn()
        except Exception as e:
            print(f"[{name}] scrape failed: {e}", file=sys.stderr)
            items = []
        items = reconcile(name, items, seen)
        print(f"[{name}] {len(items)} items")
        sections.append((name, url, items))

    save_seen(seen)
    html = build_html(sections)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
