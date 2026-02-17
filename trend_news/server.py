import os
from datetime import datetime
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.core.database import DatabaseManager

app = FastAPI(
    title="TrendRadar API",
    description="API for accessing news trends and scraped data (compatible style with Alpha Vantage)",
    version="1.0.0",
)

# Initialize Database Manager
# Assuming the DB is in output directory as configured in main.py
DB_PATH = os.path.join(os.path.dirname(__file__), "output", "trend_news.db")
if not os.path.exists(DB_PATH):
    # Fallback to check relative path if running from root
    DB_PATH = os.path.join("output", "trend_news.db")

db_manager = DatabaseManager(DB_PATH)


class NewsItem(BaseModel):
    title: str
    url: str
    time_published: str
    summary: Optional[str] = ""
    banner_image: Optional[str] = None
    source: str
    category_within_source: Optional[str] = "General"
    source_domain: Optional[str] = ""
    topics: List[str] = []
    overall_sentiment_score: float = 0.0
    overall_sentiment_label: str = "Neutral"
    relevance_score: int = 1


class NewsSentimentResponse(BaseModel):
    items: str
    sentiment_score_definition: str = "x <= -0.35: Bearish; -0.35 < x <= -0.15: Somewhat-Bearish; -0.15 < x < 0.15: Neutral; 0.15 <= x < 0.35: Somewhat-Bullish; x >= 0.35: Bullish"
    relevance_score_definition: str = "0 < x <= 1: with a higher score indicating higher relevance."
    feed: List[NewsItem]


from src.utils.sentiment import get_sentiment
from src.core.sentiment_learning import SentimentLearningManager, DynamicLexiconManager
from src.core.keyword_extractor import KeywordExtractor
from src.core.labeling_pipeline import LabelingPipeline

# Initialize learning system
learning_manager = SentimentLearningManager(DB_PATH)
lexicon_manager = DynamicLexiconManager(learning_manager)
keyword_extractor = KeywordExtractor(DB_PATH)
labeling_pipeline = LabelingPipeline(DB_PATH)

@app.get("/", tags=["Root"])
def read_root():
    return {"message": "Welcome to TrendRadar API"}


@app.get("/query", response_model=NewsSentimentResponse, tags=["Alpha Vantage Compatible"])
def get_news_sentiment(
    function: str = Query(..., description="The function to perform. Supported: NEWS_SENTIMENT"),
    tickers: Optional[str] = Query(None, description="The stock ticker to filter by (Currently maps to source_id or title search)"),
    topics: Optional[str] = Query(None, description="The topics to filter by"),
    time_from: Optional[str] = Query(None, description="Start time (YYYYMMDDTHHMM)"),
    time_to: Optional[str] = Query(None, description="End time (YYYYMMDDTHHMM)"),
    limit: int = Query(50, description="Limit number of results"),
    apikey: Optional[str] = Query(None, description="API Key (Ignored for now)")
):
    """
    Mock endpoint compatible with Alpha Vantage NEWS_SENTIMENT.
    """
    if function != "NEWS_SENTIMENT":
         raise HTTPException(status_code=400, detail="Only NEWS_SENTIMENT function is supported currently.")

    # Convert Alpha Vantage time format (YYYYMMDDTHHMM) to ISO format (YYYY-MM-DDTHH:MM:SS) for DB
    start_date_iso = None
    end_date_iso = None
    
    if time_from:
        try:
            # Parse YYYYMMDDTHHMM
            dt = datetime.strptime(time_from, "%Y%m%dT%H%M")
            start_date_iso = dt.isoformat()
        except ValueError:
            # Try simple YYYYMMDD
             try:
                dt = datetime.strptime(time_from, "%Y%m%d")
                start_date_iso = dt.isoformat()
             except ValueError:
                pass # Ignore invalid format

    if time_to:
        try:
            dt = datetime.strptime(time_to, "%Y%m%dT%H%M")
            end_date_iso = dt.isoformat()
        except ValueError:
             try:
                dt = datetime.strptime(time_to, "%Y%m%d")
                end_date_iso = dt.isoformat()
             except ValueError:
                pass

    raw_news = db_manager.get_filtered_news(
        start_date=start_date_iso,
        end_date=end_date_iso,
        tickers=tickers,   # searched against news titles via alias mapping
        limit=limit
    )

    feed_items = []
    for item in raw_news:
        # Transform DB item to Alpha Vantage style NewsItem
        source_id = item.get("source_id", "Unknown")
        title = item.get("title", "")
        
        # Calculate sentiment on the fly (Level 2 Solution)
        # In a production environment, this should be pre-calculated and stored in DB
        sentiment_score, sentiment_label = get_sentiment(title)
        
        news_item = NewsItem(
            title=title,
            url=item.get("url", ""),
            time_published=item.get("crawled_at", "").replace("-", "").replace(":", ""),
            source=source_id,
            source_domain=source_id,
            summary=f"Ranked: {item.get('ranks', '')}",
            topics=[topics] if topics else [],
            overall_sentiment_score=sentiment_score,
            overall_sentiment_label=sentiment_label,
            relevance_score=item.get("relevance_score", 1),
        )
        feed_items.append(news_item)

    return NewsSentimentResponse(
        items=str(len(feed_items)),
        feed=feed_items
    )

@app.get("/api/v1/news", tags=["Native API"])
def get_native_news(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source: Optional[str] = None,
    tickers: Optional[str] = Query(None, description="Comma-separated ticker(s) to search in news titles, e.g. 'VIC' or 'VIC,HPG'"),
    limit: int = 50
):
    """
    Native API endpoint for getting news from database.

    - **source**: filter by exact scraper source_id (e.g. 'cafef', '24hmoney')
    - **tickers**: search news titles by stock ticker aliases (e.g. 'VIC' → searches 'Vingroup', 'VIN', ...)
    """
    return db_manager.get_filtered_news(
        start_date=start_date,
        end_date=end_date,
        source_id=source,
        tickers=tickers,
        limit=limit,
    )


# ============================================================================
# SENTIMENT LEARNING ENDPOINTS
# ============================================================================

class SentimentFeedback(BaseModel):
    news_title: str
    predicted_score: float
    predicted_label: str
    user_score: float
    user_label: str
    news_id: Optional[int] = None
    news_url: Optional[str] = None
    comment: Optional[str] = None


class KeywordApproval(BaseModel):
    keyword: str
    sentiment_type: str  # 'positive' or 'negative'
    weight: float


class LabelSubmission(BaseModel):
    queue_id: int
    user_score: float
    user_label: str
    comment: Optional[str] = None


@app.post("/api/v1/feedback", tags=["Sentiment Learning"])
def add_sentiment_feedback(feedback: SentimentFeedback):
    """
    Submit user feedback on sentiment predictions
    
    This helps the system learn and improve over time.
    """
    try:
        feedback_id = learning_manager.add_feedback(
            news_title=feedback.news_title,
            predicted_score=feedback.predicted_score,
            predicted_label=feedback.predicted_label,
            user_score=feedback.user_score,
            user_label=feedback.user_label,
            news_id=feedback.news_id,
            news_url=feedback.news_url,
            comment=feedback.comment
        )
        
        return {
            "success": True,
            "feedback_id": feedback_id,
            "message": "Feedback recorded successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/feedback/stats", tags=["Sentiment Learning"])
def get_feedback_statistics(days: int = 7):
    """
    Get sentiment prediction statistics
    """
    try:
        stats = learning_manager.get_feedback_stats(days=days)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/keywords/approve", tags=["Sentiment Learning"])
def approve_keyword(approval: KeywordApproval):
    """
    Approve a keyword to be added to the lexicon
    """
    try:
        success = learning_manager.approve_keyword(
            keyword=approval.keyword,
            sentiment_type=approval.sentiment_type,
            weight=approval.weight
        )
        
        if success:
            # Refresh lexicon cache
            lexicon_manager.refresh_cache()
            return {
                "success": True,
                "message": f"Keyword '{approval.keyword}' approved"
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to approve keyword")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/keywords/suggestions", tags=["Sentiment Learning"])
def get_keyword_suggestions(
    days: int = 30,
    min_frequency: int = 3,
    limit: int = 50
):
    """
    Get suggested keywords extracted from feedback data
    """
    try:
        patterns = keyword_extractor.analyze_sentiment_patterns(
            days=days,
            min_frequency=min_frequency
        )
        
        # Limit results
        return {
            "positive": patterns['positive'][:limit],
            "negative": patterns['negative'][:limit]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/keywords/approved", tags=["Sentiment Learning"])
def get_approved_keywords():
    """
    Get all approved learned keywords
    """
    try:
        keywords = learning_manager.get_approved_keywords()
        return keywords
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/lexicon/combined", tags=["Sentiment Learning"])
def get_combined_lexicon():
    """
    Get combined lexicon (static + learned)
    """
    try:
        lexicon = lexicon_manager.get_combined_lexicon()
        return {
            "positive": lexicon['positive'],
            "negative": lexicon['negative'],
            "total_positive": len(lexicon['positive']),
            "total_negative": len(lexicon['negative'])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analysis/improvements", tags=["Sentiment Learning"])
def get_improvement_suggestions():
    """
    Get comprehensive improvement suggestions
    """
    try:
        suggestions = keyword_extractor.suggest_improvements()
        return suggestions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================================
# Labeling Queue Endpoints
# ============================================================================

@app.post("/api/v1/labeling/build", tags=["Labeling Queue"])
def build_labeling_queue(
    date: str = Query(default=datetime.now().strftime("%Y-%m-%d"), description="ISO date YYYY-MM-DD"),
    limit: int = Query(default=25, ge=1, le=100, description="Max items to queue"),
):
    """Score today's articles and insert the top N most uncertain into labeling_queue."""
    try:
        result = labeling_pipeline.build_daily_queue(date, limit=limit)
        return {**result, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/labeling/queue", tags=["Labeling Queue"])
def get_labeling_queue(
    date: str = Query(default=datetime.now().strftime("%Y-%m-%d"), description="ISO date YYYY-MM-DD"),
    status: Optional[str] = Query(default=None, description="Filter by status: pending|labeled|skipped"),
):
    """Return queue items for the given date, ordered by priority_rank."""
    try:
        items = labeling_pipeline.get_queue(date, status_filter=status)
        return {"date": date, "count": len(items), "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/labeling/submit", tags=["Labeling Queue"])
def submit_label(submission: LabelSubmission):
    """Submit an admin label for a queue item. Feeds directly into sentiment_feedback."""
    try:
        feedback_id = labeling_pipeline.submit_label(
            queue_id=submission.queue_id,
            user_score=submission.user_score,
            user_label=submission.user_label,
            comment=submission.comment,
        )
        return {"success": True, "feedback_id": feedback_id, "queue_id": submission.queue_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/labeling/skip/{queue_id}", tags=["Labeling Queue"])
def skip_queue_item(queue_id: int):
    """Mark a queue item as skipped."""
    try:
        labeling_pipeline.skip_item(queue_id)
        return {"success": True, "queue_id": queue_id, "status": "skipped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/labeling/stats", tags=["Labeling Queue"])
def get_labeling_stats(
    date: str = Query(default=datetime.now().strftime("%Y-%m-%d"), description="ISO date YYYY-MM-DD"),
):
    """Return summary statistics for the labeling queue on a given date."""
    try:
        stats = labeling_pipeline.get_queue_stats(date)
        return {"date": date, **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/labeling/score", tags=["Labeling Queue"])
def score_title(title: str = Query(..., description="Article title to score")):
    """Debug endpoint: compute uncertainty score for a single title."""
    try:
        result = labeling_pipeline.score_article_uncertainty(title)
        return {
            "title": title,
            "lexicon_score": result.lexicon_score,
            "uts_label": result.uts_label,
            "final_score": result.final_score,
            "final_label": result.final_label,
            "uncertainty_score": result.uncertainty_score,
            "signal_conflict": result.signal_conflict,
            "magnitude_uncertainty": result.magnitude_uncertainty,
            "match_sparsity": result.match_sparsity,
            "fasttext_label": result.fasttext_label,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
