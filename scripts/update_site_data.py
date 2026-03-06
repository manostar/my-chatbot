#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PAGES = [
    {"title": "会社概要", "url": "https://powered.co.jp/company/"},
    {"title": "事業内容", "url": "https://powered.co.jp/"},
    {"title": "私たちの強み", "url": "https://powered.co.jp/"},
    {"title": "対応業界", "url": "https://powered.co.jp/"},
    {"title": "製品システム", "url": "https://powered.co.jp/system/"},
    {"title": "塗布システム", "url": "https://powered.co.jp/system/"},
    {"title": "充填システム", "url": "https://powered.co.jp/system/"},
    {"title": "2液・3液の定量吐出", "url": "https://powered.co.jp/system/"},
    {"title": "インキ供給設備", "url": "https://powered.co.jp/system/"},
    {"title": "製品ラインナップ", "url": "https://powered.co.jp/product/"},
    {"title": "ミニエックスポンプ", "url": "https://powered.co.jp/product/"},
    {"title": "ペールポンプ・ドラムポンプ", "url": "https://powered.co.jp/product/"},
    {"title": "ガン・バルブ", "url": "https://powered.co.jp/product/"},
    {"title": "営業品目", "url": "https://powered.co.jp/company/"},
    {"title": "お問い合わせ", "url": "https://powered.co.jp/contact/"},
    {"title": "所在地", "url": "https://powered.co.jp/company/"},
]

KEYWORDS = {
    "会社概要": ["会社概要", "代表取締役", "資本金", "設立"],
    "事業内容": ["高粘度", "移送", "塗布", "充填", "トータルシステム"],
    "私たちの強み": ["強み", "提案力", "技術力", "育成力", "チャレンジ精神"],
    "対応業界": ["自動車", "医薬品", "印刷", "住宅設備", "電子部品", "精密機械"],
    "製品システム": ["塗布", "充填", "2液", "3液", "インキ供給"],
    "塗布システム": ["塗布", "線引き", "スプレー", "接着剤", "FIPG"],
    "充填システム": ["充填", "真空注入", "シリンジ", "ペール缶", "ドラム缶"],
    "2液・3液の定量吐出": ["2液", "3液", "LIM", "LSR", "ピグメント"],
    "インキ供給設備": ["インキ供給", "廃液", "純水", "輪転機"],
    "製品ラインナップ": ["ポンプ", "ガン", "バルブ", "フィルタ", "減圧弁"],
    "ミニエックスポンプ": ["ミニエックス", "世界最小", "レシプロ", "高圧圧送"],
    "ペールポンプ・ドラムポンプ": ["ペール缶", "ドラム缶", "フラットフォロープレート", "拡縮ワイパー"],
    "ガン・バルブ": ["ペンシルガン", "フローガン", "自動バルブ", "サックバック"],
    "営業品目": ["営業品目", "ピストンバルブ", "フィルター", "ディスペンサー", "ダイヤフラムポンプ"],
    "お問い合わせ": ["電話", "受付時間", "お問い合わせフォーム", "03-3493-2037"],
    "所在地": ["東京都品川区", "西五反田", "富士テクニカルセンター", "山梨県"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoweredSiteBot/1.0; +https://github.com/)",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site-data.js"


@dataclass
class PageText:
    url: str
    text: str


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_page(url: str) -> PageText:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    candidates = []
    for selector in ["main", "article", ".post-content", ".entry-content", ".content", "body"]:
        for node in soup.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) > 200:
                candidates.append(text)

    if not candidates:
        text = clean_text(soup.get_text(" ", strip=True))
    else:
        text = max(candidates, key=len)

    return PageText(url=url, text=text)


def summarize_from_keywords(page_text: str, keywords: list[str]) -> str:
    sentences = re.split(r"(?<=[。！？])", page_text)
    picked = []
    seen = set()

    for keyword in keywords:
        for sentence in sentences:
            s = clean_text(sentence)
            if not s or len(s) < 8:
                continue
            if keyword in s and s not in seen:
                picked.append(s)
                seen.add(s)
                break
        if len("".join(picked)) >= 180:
            break

    if not picked:
        fallback = clean_text(page_text[:180])
        if not fallback.endswith("。"):
            fallback += "。"
        return fallback

    summary = " ".join(picked)
    if len(summary) > 220:
        summary = summary[:220].rstrip() + "…"
    return summary


def build_records() -> list[dict[str, str]]:
    cache: dict[str, PageText] = {}
    records = []

    for page in PAGES:
        url = page["url"]
        title = page["title"]
        if url not in cache:
            cache[url] = fetch_page(url)
        summary = summarize_from_keywords(cache[url].text, KEYWORDS.get(title, [title]))
        records.append({
            "title": title,
            "url": url,
            "content": summary,
        })
    return records


def write_js(records: list[dict[str, str]]) -> None:
    content = "const siteData = " + json.dumps(records, ensure_ascii=False, indent=2) + ";\n"
    OUTPUT.write_text(content, encoding="utf-8")


def main() -> None:
    records = build_records()
    write_js(records)
    print(f"Updated {OUTPUT} with {len(records)} records.")


if __name__ == "__main__":
    main()
