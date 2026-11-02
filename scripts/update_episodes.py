#!/usr/bin/env python3
"""讀取 94AI就是愛 的 Podcast RSS，更新網站上和集數有關的所有內容。

用法：
  python3 scripts/update_episodes.py              # 從 RSS 網址抓取
  python3 scripts/update_episodes.py feed.xml     # 改讀本機檔案（測試用）

會更新：
- blog.html：<!-- EPISODES --> 集數卡片、<!-- EPCOUNT --> 集數、<!-- JSONLD --> 結構化資料
- index.html：<!-- LATEST --> 首頁最新一集
- ep/<代號>.html：每一集的獨立頁面（代號取自 Spotify 單集網址結尾，例如 e3qnfq5）
- sitemap.xml：全站頁面清單
抓取失敗或讀不到任何集數時，不改動檔案並以錯誤結束。
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

RSS_URL = "https://anchor.fm/s/10a38ec70/podcast/rss"
ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "blog.html"
HOME = ROOT / "index.html"   # 首頁「作戰頻道」卡片上的最新一集
EP_DIR = ROOT / "ep"          # 單集頁資料夾，整個由這支腳本產生
SITEMAP = ROOT / "sitemap.xml"
SITE = "https://94ai.com.tw"
SHOW_URL = "https://open.spotify.com/show/1CwyMTXfiHIjhj9Oq0XThv"
YOUTUBE_URL = "https://www.youtube.com/@only94ai"
APPLE_URL = "https://podcasts.apple.com/tw/podcast/94ai%E5%B0%B1%E6%98%AF%E6%84%9B/id1887442296"
KKBOX_URL = "https://podcast.kkbox.com/tw/channel/L-HsHJjN4GogswW-b4"
CSS_VER = "20261102a"         # 與其他頁面的 style.css 版本號一致
JS_VER = "20261031e"
START = "<!-- EPISODES:START -->"
END = "<!-- EPISODES:END -->"
SHOW_FIRST = 3          # 一開始直接顯示的集數，其餘收進「看更早的集數」
EXCERPT_LEN = 72        # 卡片上摘要的字數
META_DESC_LEN = 110     # 單集頁 meta description 字數
JSONLD_EPISODES = 20    # 作戰頻道頁結構化資料裡列出的最新集數
STATIC_PAGES = ["/", "/blog.html", "/tools.html", "/contact.html"]
TAIPEI = timezone(timedelta(hours=8))
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


class _Text(HTMLParser):
    """把 RSS 介紹裡的 HTML 轉成一行一段的純文字。"""

    BREAKS = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BREAKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BREAKS:
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def to_lines(raw):
    p = _Text()
    p.feed(raw or "")
    text = "".join(p.out).replace("\r", "")
    return [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


def duration_secs(value):
    if not value:
        return 0
    parts = [int(x) for x in value.strip().split(":") if x.isdigit()]
    if not parts:
        return 0
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[-3] * 3600 + parts[-2] * 60 + parts[-1]


TAG_RE = re.compile(r"^\s*[【\[]([^】\]]{1,24})[】\]]\s*")


def split_tag(title):
    """把標題開頭的【標籤】拆出來：回傳（標籤, 標題）。網站顯示用，不改 Spotify 原始標題。"""
    m = TAG_RE.match(title)
    if not m:
        return "", title
    tag = re.sub(r"94\s*ai", "", m.group(1), flags=re.I)
    tag = re.sub(r"\s+", " ", tag).strip(" ｜|・-")
    rest = title[m.end():].strip()
    return tag, (rest or title)


def episode_id(link, guid):
    """單集頁的檔名：Spotify 單集網址結尾的代號（例：…-e3qnfq5 → e3qnfq5）。"""
    m = re.search(r"-(e[0-9a-z]{4,12})/?$", link)
    if m:
        return m.group(1)
    return re.sub(r"[^0-9a-z]", "", (guid or link).lower())[:16]


def load_feed(arg):
    if arg:
        return Path(arg).read_bytes()
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "94ai-site-updater"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def parse(data):
    root = ET.fromstring(data)
    eps = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        date = iso = ""
        pub = item.findtext("pubDate")
        if pub:
            try:
                dt = parsedate_to_datetime(pub).astimezone(TAIPEI)
                date, iso = dt.strftime("%Y/%m/%d"), dt.strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                date = iso = ""
        enc = item.find("enclosure")
        secs = duration_secs(item.findtext(f"{ITUNES}duration"))
        mins = max(1, round(secs / 60)) if secs else 0
        tag, title = split_tag(title)
        eps.append({
            "id": episode_id(link, item.findtext("guid")),
            "tag": tag,
            "title": title,
            "link": link,
            "audio": enc.get("url", "") if enc is not None else "",
            "date": date,
            "iso": iso,
            "mins": mins,
            "duration": f"{mins} 分鐘" if mins else "",
            "lines": to_lines(item.findtext("description") or ""),
        })
    # 代號重複時加上序號，避免兩集寫到同一個檔案
    seen = {}
    for ep in eps:
        n = seen.get(ep["id"], 0)
        seen[ep["id"]] = n + 1
        if n:
            ep["id"] = f"{ep['id']}-{n + 1}"
    return eps


def ep_path(ep):
    return f"/ep/{ep['id']}.html"


def meta_line(ep):
    e = html.escape
    meta = e(" ・ ".join(x for x in (ep["date"], ep["duration"]) if x))
    if ep["tag"]:
        meta = f"<span class=\"ep-tag\">{e(ep['tag'])}</span>" + meta
    return meta


def is_hashtags(line):
    return line.startswith("#") and all(w.startswith("#") for w in line.split())


# ---------- 作戰頻道頁的集數卡片 ----------

def card(ep):
    e = html.escape
    first = ep["lines"][0] if ep["lines"] else ""
    excerpt = first if len(first) <= EXCERPT_LEN else first[:EXCERPT_LEN].rstrip() + "…"
    full = "\n".join(f"                <p>{e(ln)}</p>" for ln in ep["lines"])
    details = ""
    if len(ep["lines"]) > 1 or len(first) > EXCERPT_LEN:
        details = (
            "\n              <details class=\"ep-more\">\n"
            "                <summary>看完整介紹</summary>\n"
            f"{full}\n"
            "              </details>"
        )
    return (
        "            <article class=\"ep\">\n"
        f"              <p class=\"ep-meta\">{meta_line(ep)}</p>\n"
        f"              <h3><a href=\"{ep_path(ep)}\">{e(ep['title'])}</a></h3>\n"
        f"              <p class=\"ep-excerpt\">{e(excerpt)}</p>"
        f"{details}\n"
        f"              <a class=\"btn ep-listen\" href=\"{e(ep['link'], quote=True)}\" target=\"_blank\" rel=\"noopener\">收聽這一集</a>\n"
        "            </article>"
    )


def render(eps):
    first, rest = eps[:SHOW_FIRST], eps[SHOW_FIRST:]
    out = [START, f"          <p class=\"ep-count\">目前共 {len(eps)} 集，最新的在最前面。</p>",
           "          <div class=\"ep-list\">"]
    out += [card(x) for x in first]
    out.append("          </div>")
    if rest:
        out.append("          <details class=\"ep-older\">")
        out.append(f"            <summary>看更早的集數（{len(rest)} 集）</summary>")
        out.append("            <div class=\"ep-list\">")
        out += [card(x) for x in rest]
        out.append("            </div>")
        out.append("          </details>")
    out.append("          " + END)
    return "\n".join(out)


def series_jsonld(eps):
    """作戰頻道頁的結構化資料：告訴 Google 這是一個 Podcast 節目與它的集數。"""
    data = {
        "@context": "https://schema.org",
        "@type": "PodcastSeries",
        "name": "94AI就是愛",
        "url": f"{SITE}/blog.html",
        "description": "沒有主持人的 Podcast，兩個 AI 自己聊 AI 科技新聞與冷知識，每週二更新。",
        "inLanguage": "zh-TW",
        "image": f"{SITE}/images/og-image.jpg",
        "webFeed": RSS_URL,
        "author": {"@type": "Organization", "name": "94AI", "url": f"{SITE}/"},
        "sameAs": [SHOW_URL, APPLE_URL, KKBOX_URL, YOUTUBE_URL],
        "episode": [],
    }
    for ep in eps[:JSONLD_EPISODES]:
        item = {"@type": "PodcastEpisode", "name": ep["title"], "url": SITE + ep_path(ep)}
        if ep["iso"]:
            item["datePublished"] = ep["iso"]
        if ep["lines"]:
            item["description"] = ep["lines"][0]
        data["episode"].append(item)
    return script_jsonld(data, "  ")


def script_jsonld(data, indent):
    body = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    body = "\n".join(indent + ln for ln in body.split("\n"))
    return f'<script type="application/ld+json">\n{body}\n{indent}</script>'


# ---------- 單集頁 ----------

def summary_text(ep, limit):
    text = "".join(ln for ln in ep["lines"] if not is_hashtags(ln))
    text = text or ep["title"]
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def neighbor(ep, label, cls):
    if not ep:
        return ""
    return (f"          <a class=\"{cls}\" href=\"{ep_path(ep)}\"><span>{label}</span>"
            f"<strong>{html.escape(ep['title'])}</strong></a>\n")


def episode_page(ep, newer, older):
    e = html.escape
    url = SITE + ep_path(ep)
    desc = summary_text(ep, META_DESC_LEN)
    data = {
        "@context": "https://schema.org",
        "@type": "PodcastEpisode",
        "name": ep["title"],
        "url": url,
        "inLanguage": "zh-TW",
        "description": summary_text(ep, 300),
        "partOfSeries": {"@type": "PodcastSeries", "name": "94AI就是愛", "url": f"{SITE}/blog.html"},
    }
    if ep["iso"]:
        data["datePublished"] = ep["iso"]
    if ep["mins"]:
        data["timeRequired"] = f"PT{ep['mins']}M"
    if ep["audio"]:
        data["associatedMedia"] = {"@type": "MediaObject", "contentUrl": ep["audio"]}

    body = []
    for ln in ep["lines"]:
        cls = " class=\"ep-hashtags\"" if is_hashtags(ln) else ""
        body.append(f"          <p{cls}>{e(ln)}</p>")
    body_html = "\n".join(body) or f"          <p>{e(ep['title'])}</p>"
    player = (f"          <audio class=\"ep-player\" controls preload=\"none\" src=\"{e(ep['audio'], quote=True)}\"></audio>\n"
              if ep["audio"] else "")
    nav = neighbor(older, "‹ 上一集", "ep-prev") + neighbor(newer, "下一集 ›", "ep-next")
    nav_html = f"        <nav class=\"ep-nav\" aria-label=\"其他集數\">\n{nav}        </nav>\n" if nav else ""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{e(ep['title'])}｜94AI就是愛 Podcast</title>
  <meta name="description" content="{e(desc, quote=True)}">
  <meta name="robots" content="index,follow">
  <meta name="theme-color" content="#1A4BB0">
  <link rel="canonical" href="{url}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="94AI">
  <meta property="og:title" content="{e(ep['title'], quote=True)}">
  <meta property="og:description" content="{e(desc, quote=True)}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{SITE}/images/og-image.jpg">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" type="image/png" href="/images/favicon.png">
  <link rel="apple-touch-icon" href="/images/apple-touch-icon.png">
  <link rel="stylesheet" href="/assets/style.css?v={CSS_VER}">
  {script_jsonld(data, "  ")}
</head>
<body>
  <a class="skip-link" href="#main">跳到主要內容</a>
  <header class="site-header">
    <div class="container">
      <a href="/index.html" class="brand" aria-label="94AI 首頁">94<span class="brand-ai">AI</span></a>
      <nav class="site-nav" aria-label="主選單">
        <ul>
          <li><a href="/tools.html"><span class="nav-main">英雄裝備</span><span class="nav-sub">小工具</span></a></li>
          <li><a href="/blog.html" aria-current="page"><span class="nav-main">作戰頻道</span><span class="nav-sub">Podcast</span></a></li>
          <li><a href="/contact.html"><span class="nav-main">加入聯盟</span><span class="nav-sub">電子報</span></a></li>
        </ul>
      </nav>
    </div>
  </header>
  <main id="main">
    <div class="container">
      <article class="ep-page">
        <p class="crumb"><a href="/blog.html">作戰頻道</a> › 94AI就是愛 Podcast</p>
        <div class="ep-hero">
          <p class="ep-meta">{meta_line(ep)}</p>
          <h1>{e(ep['title'])}</h1>
{player}          <div class="ep-actions">
            <a class="btn" href="{e(ep['link'], quote=True)}" target="_blank" rel="noopener">在 Spotify 收聽</a>
            <a class="btn btn-ghost" href="/blog.html">看所有集數</a>
          </div>
        </div>
        <section class="ep-body">
          <h2>這一集在聊什麼</h2>
{body_html}
        </section>
{nav_html}      </article>
      <div class="gear-cta">
        <p>新集數上線時，第一個通知你。</p>
        <a class="btn" href="/contact.html">加入聯盟</a>
      </div>
    </div>
  </main>
  <footer class="site-footer">
    <nav class="footer-social" aria-label="94AI 社群與收聽平台">
      <a href="https://www.threads.com/@only94ai" target="_blank" rel="noopener">Threads</a>
      <a href="https://www.instagram.com/only94ai/" target="_blank" rel="noopener">Instagram</a>
      <a href="https://www.youtube.com/@only94ai" target="_blank" rel="noopener">YouTube</a>
      <a href="https://open.spotify.com/show/1CwyMTXfiHIjhj9Oq0XThv" target="_blank" rel="noopener">Spotify</a>
    </nav>
    <p>I AM HERE! ｜ 94AI.COM.TW ｜ ONE FOR ALL © 2026 ｜ BEYOND THE LIMIT!</p>
  </footer>
  <button id="backToTop" type="button" aria-label="回到頂端" title="回到頂端">▲</button>
  <script src="/assets/main.js?v={JS_VER}" defer></script>
</body>
</html>
"""


def write_episode_pages(eps):
    EP_DIR.mkdir(exist_ok=True)
    keep = set()
    changed = 0
    for i, ep in enumerate(eps):
        newer = eps[i - 1] if i > 0 else None
        older = eps[i + 1] if i + 1 < len(eps) else None
        path = EP_DIR / f"{ep['id']}.html"
        keep.add(path.name)
        content = episode_page(ep, newer, older)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            changed += 1
    removed = 0
    for old in EP_DIR.glob("*.html"):
        if old.name not in keep:   # RSS 裡已經沒有的集數
            old.unlink()
            removed += 1
    print(f"單集頁：共 {len(eps)} 頁，更新 {changed} 頁，移除 {removed} 頁")


# ---------- sitemap ----------

def write_sitemap(eps):
    old = SITEMAP.read_text(encoding="utf-8") if SITEMAP.exists() else ""
    prev = dict(re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]*)</lastmod>", old))
    latest = eps[0]["iso"]
    rows = []
    for p in STATIC_PAGES:
        loc = SITE + p
        lastmod = latest if p in ("/", "/blog.html") and latest else prev.get(loc, latest)
        rows.append((loc, lastmod))
    rows += [(SITE + ep_path(ep), ep["iso"]) for ep in eps]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in rows:
        out.append("  <url>")
        out.append(f"    <loc>{loc}</loc>")
        if lastmod:
            out.append(f"    <lastmod>{lastmod}</lastmod>")
        out.append("  </url>")
    out.append("</urlset>")
    new = "\n".join(out) + "\n"
    if new != old:
        SITEMAP.write_text(new, encoding="utf-8")
        print(f"sitemap.xml 已更新：共 {len(rows)} 頁")


def main():
    eps = parse(load_feed(sys.argv[1] if len(sys.argv) > 1 else None))
    if not eps:
        sys.exit("RSS 裡沒有讀到任何集數，不更新頁面。")
    page = PAGE.read_text(encoding="utf-8")
    if START not in page or END not in page:
        sys.exit("blog.html 找不到集數清單的標記，不更新頁面。")
    a = page.index(START)
    b = page.index(END) + len(END)
    new = page[:a] + render(eps) + page[b:]
    new = re.sub(r"(<!-- EPCOUNT:START -->).*?(<!-- EPCOUNT:END -->)",
                 lambda m: m.group(1) + str(len(eps)) + m.group(2), new, flags=re.S)
    new = re.sub(r"(<!-- JSONLD:START -->).*?(<!-- JSONLD:END -->)",
                 lambda m: m.group(1) + "\n  " + series_jsonld(eps) + "\n  " + m.group(2), new, flags=re.S)
    if new != page:
        PAGE.write_text(new, encoding="utf-8")
        print(f"已更新：共 {len(eps)} 集")
    else:
        print(f"沒有變動：共 {len(eps)} 集")

    if HOME.exists():
        home = HOME.read_text(encoding="utf-8")
        m = re.search(r"(<!-- LATEST:START -->).*?(<!-- LATEST:END -->)", home, re.S)
        if m:
            latest = m.group(1) + html.escape(eps[0]["title"]) + m.group(2)
            new_home = home[:m.start()] + latest + home[m.end():]
            if new_home != home:
                HOME.write_text(new_home, encoding="utf-8")
                print("首頁最新一集已更新")

    write_episode_pages(eps)
    write_sitemap(eps)


if __name__ == "__main__":
    main()
