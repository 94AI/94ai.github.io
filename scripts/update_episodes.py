#!/usr/bin/env python3
"""讀取 94AI就是愛 的 Podcast RSS，更新 blog.html（作戰頻道頁）裡的集數清單。

用法：
  python3 scripts/update_episodes.py              # 從 RSS 網址抓取
  python3 scripts/update_episodes.py feed.xml     # 改讀本機檔案（測試用）

只會改寫 blog.html 中 <!-- EPISODES:START --> 與 <!-- EPISODES:END --> 之間的內容。
抓取失敗或讀不到任何集數時，不改動檔案並以錯誤結束。
"""
import html
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
START = "<!-- EPISODES:START -->"
END = "<!-- EPISODES:END -->"
SHOW_FIRST = 6          # 一開始直接顯示的集數，其餘收進「看更早的集數」
EXCERPT_LEN = 72        # 卡片上摘要的字數
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
    return [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


def fmt_duration(value):
    if not value:
        return ""
    parts = [int(x) for x in value.strip().split(":") if x.isdigit()]
    if len(parts) == 1:
        secs = parts[0]
    elif len(parts) == 2:
        secs = parts[0] * 60 + parts[1]
    else:
        secs = parts[-3] * 3600 + parts[-2] * 60 + parts[-1]
    mins = max(1, round(secs / 60))
    return f"{mins} 分鐘"


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
        date = ""
        pub = item.findtext("pubDate")
        if pub:
            try:
                date = parsedate_to_datetime(pub).astimezone(TAIPEI).strftime("%Y/%m/%d")
            except (TypeError, ValueError):
                date = ""
        lines = to_lines(item.findtext("description") or "")
        tag, title = split_tag(title)
        eps.append({
            "tag": tag,
            "title": title,
            "link": link,
            "date": date,
            "duration": fmt_duration(item.findtext(f"{ITUNES}duration")),
            "lines": lines,
        })
    return eps


def card(ep):
    e = html.escape
    meta = e(" ・ ".join(x for x in (ep["date"], ep["duration"]) if x))
    if ep["tag"]:
        meta = f"<span class=\"ep-tag\">{e(ep['tag'])}</span>" + meta
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
        f"              <p class=\"ep-meta\">{meta}</p>\n"
        f"              <h3>{e(ep['title'])}</h3>\n"
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


if __name__ == "__main__":
    main()
