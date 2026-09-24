"""
Hỏi nhanh Gemini có Google Search grounding — dùng để ĐỐI CHIẾU chéo với kết quả của Claude.
In ra JSON: {"model", "answer", "sources":[{"title","uri"}], "search_queries":[...]}

Dùng: GEMINI_API_KEY=... python ask_gemini.py "câu hỏi" [--model gemini-3.8-flash]
"""
import argparse
import json
import os
import sys


def ask(question: str, model: str) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                      temperature=0.2)
    prompt = ("Trả lời bằng tiếng Việt, chỉ dựa trên kết quả Google Search; ghi rõ tổ chức công bố và "
              "thời điểm cho mỗi số liệu; nếu không có nguồn xác nhận thì nói rõ. Câu hỏi: " + question)
    resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
    sources, queries = [], []
    cand = resp.candidates[0] if resp.candidates else None
    gm = getattr(cand, "grounding_metadata", None) if cand else None
    if gm:
        queries = list(gm.web_search_queries or [])
        for ch in gm.grounding_chunks or []:
            web = getattr(ch, "web", None)
            if web and web.uri:
                sources.append({"title": web.title, "uri": web.uri})
    return {"model": model, "answer": resp.text or "", "sources": sources, "search_queries": queries}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    a = ap.parse_args()
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("Thiếu GEMINI_API_KEY")
    print(json.dumps(ask(a.question, a.model), ensure_ascii=False, indent=2))
