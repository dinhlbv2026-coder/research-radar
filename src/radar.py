"""
Research Radar — quét xu hướng định kỳ bằng Gemini (Google Search grounding) + OpenAlex (trắc lượng thư mục).

Nguyên tắc thiết kế:
  1. Gemini chỉ được viết từ kết quả tìm kiếm thật; mọi nguồn lấy từ grounding metadata, không để mô hình tự bịa URL.
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
import time
from pathlib import Path

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


# ------------------------------------------------------------------ Gemini ---
PROMPT = """Bạn là chuyên viên nghiên cứu xu hướng cho một nghiên cứu sinh Tiến sĩ Quản trị kinh doanh,
đồng thời là quản lý kinh doanh bảo hiểm nhân thọ tại Việt Nam.
Hôm nay là {today}. Hãy dùng Google Search để quét các diễn biến trong khoảng {days} ngày gần nhất về:

CHỦ ĐỀ: {name}
PHẠM VI TÌM: {query}
THỊ TRƯỜNG ƯU TIÊN: {market}

Yêu cầu bắt buộc:
- Chỉ nêu sự kiện/số liệu có trong kết quả tìm kiếm; mỗi ý phải ghi rõ tổ chức công bố và ngày/tháng.
- Không suy diễn số liệu; nếu không tìm được bằng chứng thì ghi "chưa tìm thấy nguồn xác nhận".
- Không dùng từ sáo rỗng ("then chốt", "toàn diện", "bức tranh toàn cảnh", "mở ra hướng đi mới").
- Không viết URL (hệ thống tự gắn nguồn).

Trình bày bằng tiếng Việt, Markdown, đúng cấu trúc:

### Các xu hướng nổi bật (5–7 xu hướng)
Với mỗi xu hướng:
**Tên xu hướng** — Mức tín hiệu: Mạnh / Trung bình / Yếu
- Diễn biến: (sự kiện cụ thể, ai, khi nào)
- Bằng chứng định lượng: (số liệu + đơn vị công bố + thời điểm)
- Insight xã hội/khách hàng: (động cơ hoặc mâu thuẫn hành vi đằng sau)
- Câu hỏi nghiên cứu tiềm năng: (1 câu, có biến độc lập/phụ thuộc gợi ý)
- Hàm ý kinh doanh: (1 hành động cụ thể cho đội kinh doanh)

Tiêu chí mức tín hiệu: Mạnh = ≥2 nguồn độc lập uy tín + có số liệu; Trung bình = 1 nguồn uy tín hoặc nhiều tin chưa có số liệu;
Yếu = tin đơn lẻ/ý kiến.

### Tín hiệu yếu cần theo dõi
(2–3 dòng)
"""


def gemini_scan(topic: dict, settings: dict) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = PROMPT.format(today=TODAY.isoformat(), days=settings["lookback_days"],
                           name=topic["name"], query=" ".join(topic["gemini_query"].split()),
                           market=settings["market_focus"])
    config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                         temperature=0.3)
    models = [settings["gemini_model"], *settings.get("gemini_fallback_models", [])]
    last_err = None
    for model in models:
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=config)
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
                return {"model": model, "text": resp.text or "", "sources": sources,
                        "search_queries": queries}
            except Exception as e:  # noqa: BLE001 — thử lại / đổi mô hình
                last_err = e
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Gemini lỗi trên mọi mô hình: {last_err}")


# ------------------------------------------------------------------ Report ---
def fmt_growth(g: dict) -> str:
    years = " | ".join(str(y) for y in g["series"])
    vals = " | ".join(str(v) for v in g["series"].values())
    cagr = f"{g['cagr'] * 100:.1f}%/năm" if g["cagr"] is not None else "không tính được"
    rel = f"{g['rel_cagr'] * 100:+.1f}%/năm" if g.get("rel_cagr") is not None else "n/a"
    return (f"*Từ khoá:* `{g['query']}` — CAGR thô {g['cagr_window']}: **{cagr}** · "
            f"CAGR chuẩn hoá theo tổng CSDL: **{rel}** (>0 = chủ đề tăng nhanh hơn mặt bằng chung)\n\n"
            f"| {years} |\n|{'---|' * len(g['series'])}\n| {vals} |\n")


def build_topic_md(topic: dict, res: dict) -> str:
    md = [f"## {topic['name']}\n"]
    gem = res.get("gemini")
    if gem:
        md.append(gem["text"].strip() + "\n")
        if gem["sources"]:
            md.append("**Nguồn (từ Google Search grounding):**\n")
            md += [f"{i}. [{s['title']}]({s['uri']})" for i, s in enumerate(gem["sources"], 1)]
            md.append("")
        md.append(f"<sub>Mô hình: {gem['model']} · Truy vấn: {'; '.join(gem['search_queries'][:6])}</sub>\n")
    elif res.get("gemini_error"):
        md.append(f"> ⚠️ Không quét được bằng Gemini: {res['gemini_error']}\n")

    md.append("### Tín hiệu trắc lượng thư mục (OpenAlex)\n")
    md.append("> Chỉ dùng để nhận diện độ 'nóng' của chủ đề trong học thuật; không dùng làm cơ sở nội dung lược khảo.\n")
    for g in res.get("growth", []):
        md.append(fmt_growth(g))
    if res.get("top_cited"):
        md.append("**Bài được trích dẫn nhiều nhất 3 năm gần đây** (cần kiểm tra toàn văn, tạp chí, tình trạng rút bài):\n")
        for p in res["top_cited"]:
            doi = p["doi"] or p["openalex"]
            md.append(f"- {p['title']} ({p['year']}) — {p['source'] or 'n/a'} — {p['cited_by']} trích dẫn — {doi}")
        md.append("")
    if res.get("openalex_error"):
        md.append(f"> ⚠️ OpenAlex lỗi: {res['openalex_error']}\n")
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

    # Bảng xếp hạng độ nóng học thuật (CAGR từ khoá chính)
    rank = []
    for t in topics:
        g = (results[t["id"]].get("growth") or [None])[0]
        if g and g.get("rel_cagr") is not None:
            rank.append((g["rel_cagr"], t["name"], g["query"], g["cagr"]))
    rank.sort(reverse=True)

    header = [f"# Research Radar — {TODAY.isoformat()}\n",
              f"Cửa sổ quét tin: {settings['lookback_days']} ngày · Thị trường: {settings['market_focus']}\n"]
    if rank:
        header.append("### Xếp hạng độ 'nóng' học thuật (CAGR chuẩn hoá, từ khoá chính)\n")
        header.append("| Hạng | Chủ đề | Từ khoá | CAGR thô | CAGR chuẩn hoá |\n|---|---|---|---|---|")
        header += [f"| {i} | {n} | `{q}` | {raw * 100:.1f}% | {c * 100:+.1f}% |"
                   for i, (c, n, q, raw) in enumerate(rank, 1)]
        header.append("")
    body = [build_topic_md(t, results[t["id"]]) for t in topics]
    footer = ["---", "*Báo cáo tự động. Mọi số liệu cần đối chiếu nguồn gốc trước khi đưa vào luận án/tài liệu chính thức.*"]
    md = "\n".join(header + body + footer)

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
