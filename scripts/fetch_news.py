import argparse
import json
import sys
import time
import re
import concurrent.futures
from datetime import datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from scrapling.fetchers import Fetcher

def filter_items(items, keyword=None):
    if not keyword:
        return items
    keywords = [k.strip() for k in keyword.split(',') if k.strip()]
    pattern = '|'.join([r'\b' + re.escape(k) + r'\b' for k in keywords])
    regex = r'(?i)(' + pattern + r')'
    return [item for item in items if re.search(regex, item['title'])]

def fetch_url_content(url):
    """Fetch article content with Scrapling. Truncates to 3000 characters."""
    if not url or not url.startswith('http'):
        return ""
    try:
        page = Fetcher.get(url)
        text = page.get_all_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        return text[:3000]
    except Exception:
        return ""

def enrich_items_with_content(items, max_workers=10):
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(fetch_url_content, item['url']): item for item in items}
        for future in concurrent.futures.as_completed(future_to_item):
            item = future_to_item[future]
            try:
                content = future.result()
                if content:
                    item['content'] = content
            except Exception:
                item['content'] = ""
    return items

# --- Source Fetchers ---

def fetch_hackernews(limit=5, keyword=None):
    base_url = "https://news.ycombinator.com"
    news_items = []
    page_num = 1
    max_pages = 5

    while len(news_items) < limit and page_num <= max_pages:
        url = f"{base_url}/news?p={page_num}"
        try:
            page = Fetcher.get(url)
        except: break

        rows = page.css('.athing')
        if not rows: break

        page_items = []
        for row in rows:
            try:
                id_ = row.attrib.get('id', '')
                title_links = row.css('.titleline a')
                if not title_links: continue
                title_line = title_links[0]
                title = title_line.text
                link = title_line.attrib.get('href', '')

                score_spans = page.css(f'#score_{id_}')
                score = score_spans[0].text if score_spans else "0 points"

                age_spans = page.css(f'.age a[href="item?id={id_}"]')
                time_str = age_spans[0].text if age_spans else ""

                if link and link.startswith('item?id='): link = f"{base_url}/{link}"

                page_items.append({
                    "source": "Hacker News",
                    "title": title,
                    "url": link,
                    "heat": score,
                    "time": time_str
                })
            except: continue

        news_items.extend(filter_items(page_items, keyword))
        if len(news_items) >= limit: break
        page_num += 1
        time.sleep(0.5)

    return news_items[:limit]

def fetch_weibo(limit=5, keyword=None):
    url = "https://weibo.com/ajax/side/hotSearch"
    try:
        response = requests.get(url, headers={"Referer": "https://weibo.com/"}, timeout=10)
        data = response.json()
        items = data.get('data', {}).get('realtime', [])

        all_items = []
        for item in items:
            title = item.get('note', '') or item.get('word', '')
            if not title: continue
            heat = item.get('num', 0)
            full_url = f"https://s.weibo.com/weibo?q={quote(title)}&Refer=top"
            all_items.append({
                "source": "Weibo Hot Search",
                "title": title,
                "url": full_url,
                "heat": f"{heat}",
                "time": "Real-time"
            })
        return filter_items(all_items, keyword)[:limit]
    except Exception:
        return []

def fetch_github(limit=5, keyword=None):
    try:
        page = Fetcher.get("https://github.com/trending")
    except: return []

    items = []
    for article in page.css('article.Box-row'):
        try:
            h2s = article.css('h2 a')
            if not h2s: continue
            h2 = h2s[0]
            title = h2.get_all_text().strip().replace('\n', '').replace(' ', '')
            link = "https://github.com" + h2.attrib.get('href', '')

            descs = article.css('p')
            desc_text = descs[0].text.strip() if descs else ""

            stars_tags = article.css('a[href$="/stargazers"]')
            stars = stars_tags[0].get_all_text().strip() if stars_tags else ""

            items.append({
                "source": "GitHub Trending",
                "title": f"{title} - {desc_text}",
                "url": link,
                "heat": f"{stars} stars",
                "time": "Today"
            })
        except: continue
    return filter_items(items, keyword)[:limit]

def fetch_36kr(limit=5, keyword=None):
    try:
        page = Fetcher.get("https://36kr.com/newsflashes")
    except: return []

    items = []
    for item in page.css('.newsflash-item'):
        title_tags = item.css('.item-title')
        if not title_tags: continue
        title_tag = title_tags[0]
        title = title_tag.text.strip()
        href = title_tag.attrib.get('href', '')

        time_tags = item.css('.time')
        time_str = time_tags[0].text.strip() if time_tags else ""

        items.append({
            "source": "36Kr",
            "title": title,
            "url": f"https://36kr.com{href}" if not href.startswith('http') else href,
            "time": time_str,
            "heat": ""
        })
    return filter_items(items, keyword)[:limit]

def fetch_v2ex(limit=5, keyword=None):
    try:
        data = requests.get("https://www.v2ex.com/api/topics/hot.json", timeout=10).json()
        items = []
        for t in data:
            replies = t.get('replies', 0)
            items.append({
                "source": "V2EX",
                "title": t['title'],
                "url": t['url'],
                "heat": f"{replies} replies",
                "time": "Hot"
            })
        return filter_items(items, keyword)[:limit]
    except: return []

def fetch_tencent(limit=5, keyword=None):
    try:
        url = "https://i.news.qq.com/web_backend/v2/getTagInfo?tagId=aEWqxLtdgmQ%3D"
        data = requests.get(url, headers={"Referer": "https://news.qq.com/"}, timeout=10).json()
        items = []
        for news in data['data']['tabs'][0]['articleList']:
            items.append({
                "source": "Tencent News",
                "title": news['title'],
                "url": news.get('url') or news.get('link_info', {}).get('url'),
                "time": news.get('pub_time', '') or news.get('publish_time', '')
            })
        return filter_items(items, keyword)[:limit]
    except: return []

def fetch_wallstreetcn(limit=5, keyword=None):
    try:
        url = "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30"
        data = requests.get(url, timeout=10).json()
        items = []
        for item in data['data']['items']:
            res = item.get('resource')
            if res and (res.get('title') or res.get('content_short')):
                 ts = res.get('display_time', 0)
                 time_str = datetime.fromtimestamp(ts).strftime('%H:%M') if ts else ""
                 items.append({
                     "source": "Wall Street CN",
                     "title": res.get('title') or res.get('content_short'),
                     "url": res.get('uri'),
                     "time": time_str
                 })
        return filter_items(items, keyword)[:limit]
    except: return []

def fetch_producthunt(limit=5, keyword=None):
    try:
        response = requests.get("https://www.producthunt.com/feed", timeout=10)
        soup = BeautifulSoup(response.text, 'xml')
        if not soup.find('item'): soup = BeautifulSoup(response.text, 'html.parser')

        items = []
        for entry in soup.find_all(['item', 'entry']):
            title = entry.find('title').get_text(strip=True)
            link_tag = entry.find('link')
            url = link_tag.get('href') or link_tag.get_text(strip=True) if link_tag else ""

            pubBox = entry.find('pubDate') or entry.find('published')
            pub = pubBox.get_text(strip=True) if pubBox else ""

            items.append({
                "source": "Product Hunt",
                "title": title,
                "url": url,
                "time": pub,
                "heat": "Top Product"
            })
        return filter_items(items, keyword)[:limit]
    except: return []

def _parse_rss_feed(url, source_name):
    """Generic RSS/Atom feed parser using requests + BS4 XML."""
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'xml')
        if not soup.find('item') and not soup.find('entry'):
            soup = BeautifulSoup(response.text, 'html.parser')
        items = []
        for entry in soup.find_all(['item', 'entry']):
            title_tag = entry.find('title')
            title = title_tag.get_text(strip=True) if title_tag else ""
            if not title: continue
            link_tag = entry.find('link')
            if link_tag:
                url_val = link_tag.get('href') or link_tag.get_text(strip=True)
            else:
                url_val = ""
            pub_tag = entry.find('pubDate') or entry.find('published') or entry.find('updated')
            pub = pub_tag.get_text(strip=True) if pub_tag else ""
            items.append({
                "source": source_name,
                "title": title,
                "url": url_val,
                "time": pub,
                "heat": ""
            })
        return items
    except: return []

# --- New Sources (RSS-based) ---

def fetch_apnews(limit=5, keyword=None):
    items = _parse_rss_feed("https://feedx.net/rss/ap.xml", "AP News")
    return filter_items(items, keyword)[:limit]

def fetch_apnews_biz(limit=5, keyword=None):
    biz_keywords = "price,energy,war,oil,trade,tax,economic,economy,companies,workers,jobs,wage,labor,stock,market,inflation,gas,finance,treasury,Fed,business"
    combined = keyword + "," + biz_keywords if keyword else biz_keywords
    items = _parse_rss_feed("https://feedx.net/rss/ap.xml", "AP News Business")
    return filter_items(items, combined)[:limit]

def fetch_theconversation(limit=5, keyword=None):
    items = _parse_rss_feed("https://theconversation.com/us/articles", "The Conversation")
    return filter_items(items, keyword)[:limit]

def fetch_theconversation_biz(limit=5, keyword=None):
    items = _parse_rss_feed("https://theconversation.com/us/business.atom", "The Conversation Business")
    return filter_items(items, keyword)[:limit]

def fetch_realnews(limit=5, keyword=None):
    items = _parse_rss_feed("https://therealnews.com/feed", "The Real News")
    return filter_items(items, keyword)[:limit]

def fetch_realnews_biz(limit=5, keyword=None):
    biz_keywords = "economy,finance,market,stock,business,tariff,oil,trade,labor,union,strike,wage,inequality,poverty,workers,price,energy,jobs,cost"
    combined = keyword + "," + biz_keywords if keyword else biz_keywords
    items = _parse_rss_feed("https://therealnews.com/feed", "The Real News Business")
    return filter_items(items, combined)[:limit]

# --- Kalshi / prediction-market signal sources ---

def fetch_politico(limit=5, keyword=None):
    items = _parse_rss_feed("https://rss.politico.com/politics-news.xml", "Politico")
    return filter_items(items, keyword)[:limit]

def fetch_thehill(limit=5, keyword=None):
    items = _parse_rss_feed("https://thehill.com/feed/", "The Hill")
    return filter_items(items, keyword)[:limit]

def fetch_coindesk(limit=5, keyword=None):
    items = _parse_rss_feed("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk")
    return filter_items(items, keyword)[:limit]

def fetch_espn(limit=5, keyword=None):
    items = _parse_rss_feed("https://www.espn.com/espn/rss/news", "ESPN")
    return filter_items(items, keyword)[:limit]

def fetch_reuters(limit=5, keyword=None):
    items = _parse_rss_feed("https://feeds.reuters.com/reuters/topNews", "Reuters")
    return filter_items(items, keyword)[:limit]

def fetch_yahoofinance(limit=5, keyword=None):
    items = _parse_rss_feed("https://finance.yahoo.com/news/rssindex", "Yahoo Finance")
    return filter_items(items, keyword)[:limit]

def fetch_noaa_weather(limit=5, keyword=None):
    items = _parse_rss_feed("https://www.weather.gov/rss_page.php?site_name=nws", "NOAA Weather")
    return filter_items(items, keyword)[:limit]

def main():
    parser = argparse.ArgumentParser()
    sources_map = {
        'hackernews': fetch_hackernews, 'weibo': fetch_weibo, 'github': fetch_github,
        '36kr': fetch_36kr, 'v2ex': fetch_v2ex, 'tencent': fetch_tencent,
        'wallstreetcn': fetch_wallstreetcn, 'producthunt': fetch_producthunt,
        'apnews': fetch_apnews, 'apnews-biz': fetch_apnews_biz,
        'theconversation': fetch_theconversation, 'theconversation-biz': fetch_theconversation_biz,
        'realnews': fetch_realnews, 'realnews-biz': fetch_realnews_biz,
        'politico': fetch_politico, 'thehill': fetch_thehill,
        'coindesk': fetch_coindesk, 'espn': fetch_espn,
        'reuters': fetch_reuters, 'yahoofinance': fetch_yahoofinance,
        'noaa-weather': fetch_noaa_weather,
    }

    parser.add_argument('--source', default='all', help='Source(s) to fetch from (comma-separated)')
    parser.add_argument('--limit', type=int, default=10, help='Limit per source. Default 10')
    parser.add_argument('--keyword', help='Comma-sep keyword filter')
    parser.add_argument('--deep', action='store_true', help='Download article content for detailed summarization')

    args = parser.parse_args()

    to_run = []
    if args.source == 'all':
        to_run = list(sources_map.values())
    else:
        requested_sources = [s.strip() for s in args.source.split(',')]
        for s in requested_sources:
            if s in sources_map: to_run.append(sources_map[s])

    results = []
    for func in to_run:
        try:
            results.extend(func(args.limit, args.keyword))
        except: pass

    if args.deep and results:
        sys.stderr.write(f"Deep fetching content for {len(results)} items...\n")
        results = enrich_items_with_content(results)

    print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
