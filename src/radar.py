"""
Research Radar — quét xu hướng định kỳ bằng Gemini (Google Search grounding) + OpenAlex (trắc lượng thư mục).

Nguyên tắc thiết kế:
  1. Gemini chỉ được viết từ tin thật do hệ thống thu thập (Google News RSS — miễn phí) hoặc Google Search grounding
     (cần gói trả phí với Gemini 3.x); URL do hệ thống gắn, không để mô hình tự viết.
  2. OpenAlex chỉ dùng làm TÍN HIỆU trắc lượng (số công bố theo năm, bài được trích dẫn nhiều) — không dùng làm
     cơ sở nội dung lược khảo.
  3. Kết quả lưu thành Markdown + JSON có ngày tháng trong kho GitHub để theo dõi theo thời gian (có phiên bản).

Chạy:  python src/radar.py                 (tất cả chủ đề)
       python src/radar.py --topic life-insurance --dry-run
Biến môi trường: GEMINI_API_KEY (bắt buộc trừ --dry-run), OPENALEX_API_KEY (khuyến nghị).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "topics.yaml"
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
OPENALEX = "https://api.openalex.org"
# Tìm trong tiêu đề + tóm tắt (không phải toàn văn) để tránh kết quả lạc đề; từ khoá không được chứa dấu phẩy.

TODAY = dt.date.today()


# ---------------------------------------------------------------- OpenAlex ---
def _oa_params(extra: dict) -> dict:
    p = dict(extra)
    key = os.getenv("OPENALEX_API_KEY")
    if key:
        p["api_key"] = key
    return p


_TOTALS: dict[int, int] = {}


def openalex_totals(first: int) -> dict[int, int]:
    """Tổng số công bố toàn cơ sở dữ liệu theo năm — mẫu số để chuẩn hoá (tránh nhầm tăng trưởng
    chung của CSDL với tăng trưởng riêng của chủ đề)."""
    if not _TOTALS:
        r = requests.get(f"{OPENALEX}/works", params=_oa_params({
            "filter": f"publication_year:{first}-{TODAY.year}", "group_by": "publication_year"}), timeout=60)
        r.raise_for_status()
        _TOTALS.update({int(g["key"]): g["count"] for g in r.json().get("group_by", [])})
    return _TOTALS


def openalex_growth(query: str, years: int) -> dict:
    """Số công bố theo năm + CAGR thô + CAGR chuẩn hoá theo tổng công bố (trên các năm ĐÃ trọn vẹn)."""
    last_full = TODAY.year - 1
    first = last_full - years + 1
    params = _oa_params({
        "filter": f"title_and_abstract.search:{query},publication_year:{first}-{TODAY.year}",
        "group_by": "publication_year",
    })
    r = requests.get(f"{OPENALEX}/works", params=params, timeout=60)
    r.raise_for_status()
    counts = {int(g["key"]): g["count"] for g in r.json().get("group_by", [])}
    series = {y: counts.get(y, 0) for y in range(first, TODAY.year + 1)}
    a, b = series.get(first, 0), series.get(last_full, 0)
    n = last_full - first
    cagr = ((b / a) ** (1 / n) - 1) if a > 0 and n > 0 else None
    rel = None
    try:
        tot = openalex_totals(first)
        ta, tb = tot.get(first, 0), tot.get(last_full, 0)
        if a > 0 and ta > 0 and tb > 0 and n > 0:
            rel = ((b / tb) / (a / ta)) ** (1 / n) - 1
    except Exception:  # noqa: BLE001
        pass
    return {"query": query, "series": series, "cagr": cagr, "rel_cagr": rel,
            "cagr_window": f"{first}-{last_full}",
            "note": f"Năm {TODAY.year} chưa trọn vẹn, không đưa vào CAGR."}


def openalex_top_cited(query: str, n: int) -> list[dict]:
    """Bài được trích dẫn nhiều nhất trong 3 năm gần đây — chỉ là tín hiệu 'điểm nóng'."""
    params = _oa_params({
        "filter": f"title_and_abstract.search:{query},publication_year:{TODAY.year - 3}-{TODAY.year}",
        "sort": "cited_by_count:desc",
        "per_page": n,
        "select": "id,doi,title,publication_year,cited_by_count,primary_location",
    })
    r = requests.get(f"{OPENALEX}/works", params=params, timeout=60)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        out.append({"title": w.get("title"), "year": w.get("publication_year"),
                    "cited_by": w.get("cited_by_count"), "doi": w.get("doi"),
                    "source": src, "openalex": w.get("id")})
    return out


# -------------------------------------------------------------- Tin tức ---
def fetch_news(queries: list[str], days: int, cap: int = 40) -> list[dict]:
    """Lấy tin từ Google News RSS (miễn phí). Truy vấn có dấu tiếng Việt → bản tin VN; còn lại → bản tin quốc tế."""
    items, seen = [], set()
    for q in queries:
        vi = any(ord(c) > 127 for c in q)
        hl, gl, ceid = ("vi", "VN", "VN:vi") if vi else ("en-US", "US", "US:en")
        url = (f"https://news.google.com/rss/search?q={quote_plus(q + f' when:{days}d')}"
               f"&hl={hl}&gl={gl}&ceid={ceid}")
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 research-radar"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:  # noqa: BLE001
            print(f"  ! RSS lỗi '{q}': {e}", flush=True)
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            key = re.sub(r"\W+", " ", title.lower()).strip()
            if not title or key in seen:
                continue
            seen.add(key)
            try:
                d = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
            except Exception:  # noqa: BLE001
                d = ""
            src = it.find("source")
            items.append({"title": title, "uri": (it.findtext("link") or "").strip(), "date": d,
                          "source": (src.text if src is not None else "") or ""})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:cap]


# ------------------------------------------------------------------ Gemini ---
RULES = """Yêu cầu bắt buộc:
- Chỉ nêu sự kiện/số liệu có trong {basis}; mỗi ý phải ghi rõ tổ chức công bố và ngày/tháng.
- Không suy diễn số liệu; nếu không đủ bằng chứng thì ghi "chưa tìm thấy nguồn xác nhận".
- Không dùng từ sáo rỗng ("then chốt", "toàn diện", "bức tranh toàn cảnh", "mở ra hướng đi mới").
- Không viết URL (hệ thống tự gắn nguồn).{cite}

Trình bày bằng tiếng Việt, Markdown, đúng cấu trúc (không thêm lời chào hay kết luận):

| # | Xu hướng | Tín hiệu | Một câu vì sao đáng chú ý |
|---|---|---|---|
(5–7 dòng; cột Tín hiệu ghi đúng một trong ba: "●●● Mạnh", "●●○ Trung bình", "●○○ Yếu")

Sau bảng, mỗi xu hướng một mục:
#### <số>. <Tên xu hướng> · <●●● Mạnh | ●●○ Trung bình | ●○○ Yếu>
- Diễn biến: (sự kiện cụ thể, ai, khi nào)
- Bằng chứng định lượng: (số liệu + đơn vị công bố + thời điểm; không có thì ghi rõ)
- Insight xã hội/khách hàng: (động cơ hoặc mâu thuẫn hành vi đằng sau — ghi rõ đây là diễn giải)
- Câu hỏi nghiên cứu tiềm năng: (1 câu, có biến độc lập/phụ thuộc gợi ý)
- Hàm ý kinh doanh: (1 hành động cụ thể cho đội kinh doanh)

Tiêu chí mức tín hiệu: Mạnh = ≥2 nguồn độc lập uy tín + có số liệu; Trung bình = 1 nguồn uy tín hoặc nhiều tin chưa có số liệu;
Yếu = tin đơn lẻ/ý kiến.

#### Tín hiệu yếu cần theo dõi
(2–3 gạch đầu dòng)
"""

HEAD = """Bạn là chuyên viên nghiên cứu xu hướng cho một nghiên cứu sinh Tiến sĩ Quản trị kinh doanh,
đồng thời là quản lý kinh doanh bảo hiểm nhân thọ tại Việt Nam.
Hôm nay là {today}. Phân tích diễn biến trong khoảng {days} ngày gần nhất về:

CHỦ ĐỀ: {name}
PHẠM VI: {query}
THỊ TRƯỜNG ƯU TIÊN: {market}
"""


def _call_gemini(prompt: str, settings: dict, tools) -> tuple[str, object]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = types.GenerateContentConfig(tools=tools, temperature=0.3) if tools else \
        types.GenerateContentConfig(temperature=0.3)
    last_err = None
    for model in [settings["gemini_model"], *settings.get("gemini_fallback_models", [])]:
        for attempt in range(3):
            try:
                return model, client.models.generate_content(model=model, contents=prompt, config=config)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if "404" in str(e) or "NOT_FOUND" in str(e):
                    break  # mô hình không dùng được → chuyển mô hình dự phòng
                time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Gemini lỗi trên mọi mô hình: {last_err}")


def gemini_scan(topic: dict, settings: dict) -> dict:
    from google.genai import types

    head = HEAD.format(today=TODAY.isoformat(), days=settings["lookback_days"], name=topic["name"],
                       query=" ".join(topic["gemini_query"].split()), market=settings["market_focus"])
    mode = settings.get("search_mode", "news_rss")

    if mode == "google_search":  # cần gói trả phí cho dòng Gemini 3.x
        prompt = head + "\nHãy dùng Google Search để tìm tin.\n" + RULES.format(basis="kết quả tìm kiếm", cite="")
        model, resp = _call_gemini(prompt, settings, [types.Tool(google_search=types.GoogleSearch())])
        sources, queries = [], []
        cand = resp.candidates[0] if resp.candidates else None
        gm = getattr(cand, "grounding_metadata", None) if cand else None
        if gm:
            queries = list(gm.web_search_queries or [])
            seen = set()
            for ch in gm.grounding_chunks or []:
                web = getattr(ch, "web", None)
                if web and web.uri and web.uri not in seen:
                    seen.add(web.uri)
                    sources.append({"title": web.title, "uri": web.uri})
        return {"model": model, "mode": mode, "text": resp.text or "", "sources": sources,
                "search_queries": queries, "n_items": None}

    # Chế độ mặc định (miễn phí): Google News RSS → Gemini tổng hợp, bắt buộc trích [số]
    news = fetch_news(topic.get("news_queries", []), settings["lookback_days"])
    if not news:
        raise RuntimeError("Không lấy được tin từ Google News RSS")
    listing = "\n".join(f"[{i}] ({n['date']}, {n['source']}) {n['title']}" for i, n in enumerate(news, 1))
    prompt = (head + "\nDANH SÁCH TIN (chỉ có tiêu đề, nguồn, ngày):\n" + listing + "\n\n" +
              RULES.format(basis="DANH SÁCH TIN ở trên (chỉ dựa vào tiêu đề, không suy thêm nội dung bài)",
                           cite="\n- Sau mỗi ý phải ghi số tin làm căn cứ, dạng [3] hoặc [3][7]."))
    model, resp = _call_gemini(prompt, settings, None)
    text = resp.text or ""
    cited = sorted({int(x) for x in re.findall(r"\[(\d+)\]", text) if 1 <= int(x) <= len(news)})
    # Luôn liệt kê toàn bộ tin đầu vào để mọi nhận định đều truy vết được; đánh dấu ★ tin được trích [số].
    sources = [{"title": f"{'★ ' if i in cited else ''}[{i}] {n['title']} ({n['date']})", "uri": n["uri"]}
               for i, n in enumerate(news, 1)]
    return {"model": model, "mode": mode, "text": text, "sources": sources,
            "search_queries": topic.get("news_queries", []), "n_items": len(news), "news": news}


SUMMARY = """Dưới đây là phân tích xu hướng tuần của {n} chủ đề (đã kèm số tin [n] của từng chủ đề).
Người đọc: nghiên cứu sinh Tiến sĩ QTKD, đồng thời phụ trách kinh doanh bảo hiểm nhân thọ khu vực Đồng Tháp.
Viết bằng tiếng Việt, ngắn gọn, đúng cấu trúc Markdown sau, không lời chào, không từ sáo rỗng, không thêm số liệu mới.
KHÔNG ghi số tin dạng [n] (vì số tin khác nhau giữa các chủ đề); thay bằng tên nguồn và ngày:

**5 điểm đáng chú ý nhất tuần**
1. <chủ đề> — <một câu, có ngày/nguồn nếu có>
(đủ 5 dòng, ưu tiên tín hiệu Mạnh)

**3 việc nên làm tuần này**
- Cho luận án: <một hành động cụ thể>
- Cho đội kinh doanh: <một hành động cụ thể>
- Cần kiểm chứng thêm: <một nhận định cần mở nguồn gốc>

NỘI DUNG:
{body}
"""


def executive_summary(texts: dict[str, str], settings: dict) -> str:
    body = "\n\n".join(f"## {k}\n{v[:6000]}" for k, v in texts.items() if v)
    if not body:
        return ""
    try:
        _, resp = _call_gemini(SUMMARY.format(n=len(texts), body=body), settings, None)
        return (resp.text or "").strip()
    except Exception as e:  # noqa: BLE001
        return f"> Không tạo được tóm tắt: {str(e)[:200]}"


# ------------------------------------------------------------------ Report ---
def fmt_growth(g: dict) -> str:
    years = " | ".join(str(y) for y in g["series"])
    vals = " | ".join(str(v) for v in g["series"].values())
    cagr = f"{g['cagr'] * 100:.1f}%/năm" if g["cagr"] is not None else "không tính được"
    rel = f"{g['rel_cagr'] * 100:+.1f}%/năm" if g.get("rel_cagr") is not None else "n/a"
    return (f"*Từ khoá:* `{g['query']}` — CAGR thô {g['cagr_window']}: **{cagr}** · "
            f"CAGR chuẩn hoá theo tổng CSDL: **{rel}** (>0 = chủ đề tăng nhanh hơn mặt bằng chung)\n\n"
            f"| {years} |\n|{'---|' * len(g['series'])}\n| {vals} |\n")


def _week_label() -> str:
    y, w, _ = TODAY.isocalendar()
    return f"Tuần {w}/{y}"


def build_topic_md(idx: int, topic: dict, res: dict, img: str | None) -> str:
    md = [f'<a id="{topic["id"]}"></a>', f"## {idx}. {topic['name']}\n"]
    gem = res.get("gemini")
    if gem:
        md.append(gem["text"].strip() + "\n")
        if gem["sources"]:
            label = "Google News" if gem.get("mode") != "google_search" else "Google Search"
            md.append(f"<details><summary><b>Nguồn tin ({len(gem['sources'])} tin, {label})</b> — "
                      f"số trong [ ] khớp trích dẫn, ★ = được trích</summary>\n")
            md += [f"- [{s['title']}]({s['uri']})" for s in gem["sources"]]
            md.append("\n</details>\n")
        md.append(f"<sub>Mô hình: {gem['model']} · Truy vấn: {'; '.join(gem['search_queries'][:6])}</sub>\n")
    elif res.get("gemini_error"):
        md.append(f"> ⚠️ Không quét được tin: {res['gemini_error']}\n")

    md.append("### Học thuật đang nói gì\n")
    if img:
        md.append(f"![Xu hướng công bố — {topic['name']}]({img})\n")
    if res.get("growth"):
        md.append("| Từ khoá | Công bố năm gần nhất trọn vẹn | CAGR thô | So với mặt bằng chung |\n|---|---:|---:|---:|")
        for g in res["growth"]:
            last = g["cagr_window"].split("-")[1]
            raw = f"{g['cagr'] * 100:.0f}%" if g["cagr"] is not None else "n/a"
            rel = f"**{g['rel_cagr'] * 100:+.0f}%**" if g.get("rel_cagr") is not None else "n/a"
            md.append(f"| `{g['query']}` | {g['series'].get(int(last), 0)} ({last}) | {raw} | {rel} |")
        md.append("\n<sub>OpenAlex, tìm trong tiêu đề + tóm tắt; chỉ là tín hiệu trắc lượng, "
                  "không dùng làm cơ sở nội dung lược khảo.</sub>\n")
    if res.get("top_cited"):
        md.append("<details><summary><b>Bài được trích dẫn nhiều nhất 3 năm gần đây</b> "
                  "(cần kiểm tra toàn văn, hạng tạp chí, tình trạng rút bài)</summary>\n")
        for p in res["top_cited"]:
            doi = p["doi"] or p["openalex"]
            md.append(f"- {p['title']} ({p['year']}) — *{p['source'] or 'n/a'}* — {p['cited_by']} trích dẫn — {doi}")
        md.append("\n</details>\n")
    if res.get("openalex_error"):
        md.append(f"> ⚠️ OpenAlex lỗi: {res['openalex_error']}\n")
    md.append("[↑ Về đầu trang](#top)\n")
    return "\n".join(md)


def run(topic_filter: str | None, dry_run: bool) -> Path:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    settings, topics = cfg["settings"], cfg["topics"]
    if topic_filter:
        topics = [t for t in topics if t["id"] == topic_filter]
        if not topics:
            sys.exit(f"Không có chủ đề id={topic_filter}")

    results = {}
    for t in topics:
        print(f"→ {t['name']}", flush=True)
        res: dict = {}
        if not dry_run:
            try:
                res["gemini"] = gemini_scan(t, settings)
            except Exception as e:  # noqa: BLE001
                res["gemini_error"] = str(e)[:300]
        try:
            qs = [t["openalex_search"], *t.get("openalex_extra", [])]
            res["growth"] = [openalex_growth(q, settings["bibliometric_years"]) for q in qs]
            res["top_cited"] = openalex_top_cited(t["openalex_search"], settings["top_papers_per_topic"])
        except Exception as e:  # noqa: BLE001
            res["openalex_error"] = str(e)[:300]
        results[t["id"]] = res

    # ----- Biểu đồ -----
    import charts
    from collections import Counter

    stamp = TODAY.isoformat() + ("-dry" if dry_run else "")
    IMG = REPORTS / "img"
    IMG.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, t in enumerate(topics):
        for g in results[t["id"]].get("growth", []):
            rows.append({"topic": t["name"], "topic_idx": i, "query": g["query"], "rel": g.get("rel_cagr")})
    hot_img = None
    if any(r["rel"] is not None for r in rows):
        charts.hot_ranking(rows, IMG / f"{stamp}-hot.png",
                           "Chủ đề học thuật nào đang tăng nhanh hơn mặt bằng chung?")
        hot_img = f"img/{stamp}-hot.png"
    topic_imgs = {}
    for t in topics:
        gr = results[t["id"]].get("growth")
        if gr:
            charts.topic_trend(gr, IMG / f"{stamp}-{t['id']}.png", f"Số công bố theo năm — {t['name']}",
                               TODAY.year, color_idx=topics.index(t))
            topic_imgs[t["id"]] = f"img/{stamp}-{t['id']}.png"
    src_counter = Counter(n["source"] for t in topics
                          for n in (results[t["id"]].get("gemini") or {}).get("news", []) if n["source"])
    src_img = None
    if src_counter:
        charts.news_sources(src_counter.most_common(10), IMG / f"{stamp}-sources.png",
                            "Nguồn tin xuất hiện nhiều nhất tuần này")
        src_img = f"img/{stamp}-sources.png"

    # ----- Tóm tắt điều hành -----
    summary = "" if dry_run else executive_summary(
        {t["name"]: (results[t["id"]].get("gemini") or {}).get("text", "") for t in topics}, settings)

    rank = []
    for t in topics:
        g = (results[t["id"]].get("growth") or [None])[0]
        if g and g.get("rel_cagr") is not None:
            rank.append((g["rel_cagr"], t["name"], t["id"]))
    rank.sort(reverse=True)

    header = ['<a id="top"></a>',
              f"# Research Radar · {_week_label()}",
              f"\n> **Ngày chạy:** {TODAY.strftime('%d/%m/%Y')} · **Cửa sổ tin:** {settings['lookback_days']} ngày · "
              f"**Thị trường:** {settings['market_focus']}\n",
              f"**Bản PDF khổ A4:** [tải về](pdf/{stamp}.pdf)\n"]
    if summary:
        header += ["## Tóm tắt điều hành\n", summary, ""]
    header.append("## Mục lục\n")
    header += [f"{i}. [{t['name']}](#{t['id']})" for i, t in enumerate(topics, 1)]
    header.append("")
    if hot_img:
        header += ["## Bản đồ độ nóng học thuật\n", f"![Bản đồ độ nóng học thuật]({hot_img})\n"]
        if rank:
            header.append("| Hạng | Chủ đề (từ khoá chính) | So với mặt bằng chung |\n|---:|---|---:|")
            header += [f"| {i} | [{n}](#{tid}) | **{c * 100:+.0f}%/năm** |" for i, (c, n, tid) in enumerate(rank, 1)]
            header.append("\n<sub>CAGR chuẩn hoá = tốc độ tăng số công bố của từ khoá chia cho tốc độ tăng tổng công bố "
                          "OpenAlex, giai đoạn các năm đã trọn vẹn.</sub>\n")
    if src_img:
        header += ["## Ai đang đưa tin nhiều nhất\n", f"![Nguồn tin]({src_img})\n"]
    body = [build_topic_md(i, t, results[t["id"]], topic_imgs.get(t["id"])) for i, t in enumerate(topics, 1)]
    footer = ["---", "*Báo cáo tự động từ Google News + Gemini + OpenAlex. Mọi số liệu cần mở nguồn gốc "
              "trước khi đưa vào luận án hoặc tài liệu chính thức.*"]
    md = "\n".join(header + ["---"] + body + footer)
    for r in results.values():  # không lưu danh sách tin thô 2 lần trong JSON
        (r.get("gemini") or {}).pop("news", None)

    REPORTS.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    suffix = "-dry" if dry_run else ""
    out = REPORTS / f"{TODAY.isoformat()}{suffix}.md"
    out.write_text(md, encoding="utf-8")
    if not dry_run:
        (REPORTS / "latest.md").write_text(md, encoding="utf-8")
    (DATA / f"{TODAY.isoformat()}{suffix}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"✓ Đã ghi {out.relative_to(ROOT)}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", help="chỉ chạy một chủ đề theo id")
    ap.add_argument("--dry-run", action="store_true", help="bỏ qua Gemini, chỉ chạy OpenAlex")
    a = ap.parse_args()
    if not a.dry_run and not os.getenv("GEMINI_API_KEY"):
        sys.exit("Thiếu GEMINI_API_KEY (đặt trong GitHub Secrets hoặc biến môi trường).")
    run(a.topic, a.dry_run)
