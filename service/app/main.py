from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from fetch_news import SOURCES, enrich_items_with_content

app = FastAPI(title="news-aggregator-service")


@app.get("/health")
def health():
    return {"status": "ok", "sources": len(SOURCES)}


@app.get("/sources")
def list_sources():
    return {"sources": sorted(SOURCES.keys())}


@app.get("/news")
def get_news(
    source: str = Query("all", description="Comma-separated source names, or 'all'"),
    limit: int = Query(10, ge=1, le=50, description="Max items per source"),
    keyword: Optional[str] = Query(None, description="Comma-separated keyword filter"),
    deep: bool = Query(False, description="Fetch and attach article body content"),
):
    if source == "all":
        to_run = list(SOURCES.values())
    else:
        requested = [s.strip() for s in source.split(",") if s.strip()]
        unknown = [s for s in requested if s not in SOURCES]
        if unknown:
            raise HTTPException(400, f"Unknown source(s): {', '.join(unknown)}")
        to_run = [SOURCES[s] for s in requested]

    results = []
    for fetch in to_run:
        try:
            results.extend(fetch(limit, keyword))
        except Exception:
            pass

    if deep and results:
        results = enrich_items_with_content(results)

    return {"count": len(results), "items": results}
