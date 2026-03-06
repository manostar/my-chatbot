#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://powered.co.jp/"
ALLOWED_DOMAIN = "powered.co.jp"
SEED_URLS = [
    "https://powered.co.jp/",
    "https://powered.co.jp/company/",
    "https://powered.co.jp/system/",
    "https://powered.co.jp/product/",
    "https://powered.co.jp/contact/",
]
MAX_PAGES = 60
MAX_RECORDS = 220
MIN_TEXT_LEN = 18
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoweredCrawler/1.0; +https://github.com/)",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site-data.js"


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def same_domain(url: str) -> bool:
    try:
        return urlparse(url).netloc.endswith(ALLOWED_DOMAIN)
    except Exception:
        return False


def clean_url(url: str) -> str:
    p = urlparse(url)
    path = p.path or "/"
    return f"{p.scheme}://{p.netloc}{path}"


def extract_links(soup: BeautifulSoup, current_url: str) -> list[str]:
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full = urljoin(current_url, href)
        full = clean_url(full)
        if same_domain(full):
            links.append(full)

    seen = set()
    unique = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique.append(link)
    return unique


def extract_main_node(soup: BeautifulSoup):
    for selector in ["main", "article", ".post-content", ".entry-content", ".content", "#content"]:
        node = soup.select_one(selector)
        if node:
            return node
    return soup.body or soup


def keyword_candidates(text: str, limit: int = 12) -> list[str]:
    terms = re.findall(r"[一-龥ぁ-んァ-ヶA-Za-z0-9\-\+]{2,20}", text)
    stop = {
        "です","ます","した","する","いる","ある","こと","ため","および","または","など",
        "当社","日本","株式会社","ページ","こちら","お問い合わせ","製品","システム","会社",
        "powered","https","co","jp"
    }
    out = []
    seen = set()
    for term in terms:
        if term in stop:
            continue
        if term not in seen:
            seen.add(term)
            out.append(term)
        if len(out) >= limit:
            break
    return out


def title_from_text(page_title: str, heading: str, paragraph: str) -> str:
    if heading:
        return normalize_space(heading)[:60]
    if page_title:
        return normalize_space(page_title)[:60]
    return normalize_space(paragraph)[:60]


def classify_record(text: str, title: str) -> str:
    joined = f"{title} {text}"
    if any(word in joined for word in ["お問い合わせ", "電話", "FAX", "メール", "フォーム"]):
        return "contact"
    if any(word in joined for word in ["住所", "所在地", "本社", "センター"]):
        return "location"
    if any(word in joined for word in ["ポンプ", "ガン", "バルブ", "フィルタ", "減圧弁"]):
        return "product"
    if any(word in joined for word in ["塗布", "充填", "定量吐出", "インキ供給", "システム"]):
        return "system"
    if any(word in joined for word in ["会社概要", "事業内容", "強み", "取引先", "設立", "資本金"]):
        return "company"
    return "general"


def parse_page(url: str, html: str) -> tuple[list[dict], list[str]]:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe", "form"]):
        tag.decompose()

    page_title = normalize_space(soup.title.get_text(" ", strip=True)) if soup.title else ""
    main_node = extract_main_node(soup)
    links = extract_links(soup, url)

    records = []
    current_heading = page_title

    for node in main_node.find_all(["h1", "h2", "h3", "p", "li"]):
        text = normalize_space(node.get_text(" ", strip=True))
        if len(text) < MIN_TEXT_LEN:
            continue

        if node.name in ["h1", "h2", "h3"]:
            current_heading = text
            continue

        title = title_from_text(page_title, current_heading, text)
        keywords = keyword_candidates(f"{title} {text}")
        category = classify_record(text, title)

        records.append({
            "title": title,
            "url": url,
            "content": text[:260],
            "keywords": keywords,
            "category": category,
        })

    dedup = []
    seen = set()
    for record in records:
        key = (record["title"], record["content"])
        if key not in seen:
            seen.add(key)
            dedup.append(record)

    return dedup, links


def crawl() -> list[dict]:
    visited = set()
    queue = deque(SEED_URLS)
    all_records = []

    session = requests.Session()
    session.headers.update(HEADERS)

    while queue and len(visited) < MAX_PAGES and len(all_records) < MAX_RECORDS:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or resp.encoding
        except Exception as e:
            print(f"Skip {url}: {e}")
            continue

        records, links = parse_page(url, resp.text)
        all_records.extend(records)

        for link in links:
            if link not in visited and link not in queue:
                queue.append(link)

    final_records = []
    seen = set()
    for record in all_records:
        content_key = normalize_space(record["content"])
        if content_key in seen:
            continue
        seen.add(content_key)
        final_records.append(record)
        if len(final_records) >= MAX_RECORDS:
            break

    return final_records


def write_js(records: list[dict]) -> None:
    content = "const siteData = " + json.dumps(records, ensure_ascii=False, indent=2) + ";\n"
    OUTPUT.write_text(content, encoding="utf-8")


def main() -> None:
    records = crawl()
    if not records:
        raise RuntimeError("No records were generated.")
    write_js(records)
    print(f"Generated {len(records)} records to {OUTPUT}")


if __name__ == "__main__":
    main()
