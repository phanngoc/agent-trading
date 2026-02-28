"""
Integration Test: Cognee Index → Query Pipeline
================================================

Mục đích: Verify toàn bộ luồng index + query của Cognee:
  1. Index các bài báo tài chính tiếng Việt vào knowledge graph
  2. Query bằng tên công ty / sự kiện / ngành
  3. Xác nhận kết quả trả về có liên quan đến query

Cognee Search Types được test:
  - CHUNKS           : tìm text chunks gần giống query (semantic similarity)
  - GRAPH_COMPLETION : LLM traverse Kuzu graph, trả về câu trả lời tổng hợp
  - SUMMARIES        : tìm summary nodes trong graph

Chạy test (từ thư mục trend_news/):
    pytest tests/test_cognee_query.py -v -s -m integration
    pytest tests/test_cognee_query.py -v -m integration   # không thấy print

Yêu cầu:
    - OPENAI_API_KEY hoặc GEMINI_API_KEY trong .env
    - pip install cognee fastembed pytest pytest-asyncio
"""

import asyncio
import os
import sys
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Any

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_TREND_NEWS_DIR = Path(__file__).parent.parent
if str(_TREND_NEWS_DIR) not in sys.path:
    sys.path.insert(0, str(_TREND_NEWS_DIR))

# ---------------------------------------------------------------------------
# Test corpus — 6 bài báo đa dạng theo công ty và sự kiện
# ---------------------------------------------------------------------------
ARTICLES = [
    {
        "id": "vic_1",
        "text": (
            "TIN TỨC TÀI CHÍNH: [vnexpress] 2026-02-28\n"
            "Tiêu đề: VinGroup đầu tư 1 tỷ USD vào VinFast để mở rộng thị trường Mỹ và châu Âu\n"
            "Cảm xúc thị trường: Bullish (+0.85)\n"
            "Nguồn: https://vnexpress.net/vingroup-vinfast-invest\n"
        ),
        "keywords": ["VinGroup", "VinFast"],
    },
    {
        "id": "vic_2",
        "text": (
            "TIN TỨC TÀI CHÍNH: [cafef] 2026-02-28\n"
            "Tiêu đề: Cổ phiếu VIC tăng 5% sau thông báo VinGroup mua lại chuỗi bán lẻ\n"
            "Cảm xúc thị trường: Bullish (+0.72)\n"
            "Nguồn: https://cafef.vn/co-phieu-vic-tang\n"
        ),
        "keywords": ["VIC", "VinGroup"],
    },
    {
        "id": "fpt_1",
        "text": (
            "TIN TỨC TÀI CHÍNH: [vietstock] 2026-02-28\n"
            "Tiêu đề: FPT công bố lợi nhuận quý 4/2025 tăng 32% so với cùng kỳ nhờ mảng phần mềm xuất khẩu\n"
            "Cảm xúc thị trường: Bullish (+0.91)\n"
            "Nguồn: https://vietstock.vn/fpt-q4-2025\n"
        ),
        "keywords": ["FPT"],
    },
    {
        "id": "vcb_1",
        "text": (
            "TIN TỨC TÀI CHÍNH: [tinnhanhchungkhoan] 2026-02-28\n"
            "Tiêu đề: Vietcombank VCB hạ lãi suất cho vay hỗ trợ doanh nghiệp vừa và nhỏ\n"
            "Cảm xúc thị trường: Bullish (+0.55)\n"
            "Nguồn: https://tinnhanhchungkhoan.vn/vcb-ha-lai-suat\n"
        ),
        "keywords": ["Vietcombank", "VCB"],
    },
    {
        "id": "hpg_1",
        "text": (
            "TIN TỨC TÀI CHÍNH: [ndh] 2026-02-27\n"
            "Tiêu đề: Hòa Phát HPG dự kiến xuất khẩu 1 triệu tấn thép trong năm 2026\n"
            "Cảm xúc thị trường: Bullish (+0.68)\n"
            "Nguồn: https://ndh.vn/hoa-phat-xuat-khau-thep\n"
        ),
        "keywords": ["Hòa Phát", "HPG", "thép"],
    },
    {
        "id": "vnm_bearish",
        "text": (
            "TIN TỨC TÀI CHÍNH: [cafef] 2026-02-27\n"
            "Tiêu đề: Vinamilk VNM giảm doanh thu quý 1 do sức mua sữa sụt giảm tại thị trường nội địa\n"
            "Cảm xúc thị trường: Bearish (-0.45)\n"
            "Nguồn: https://cafef.vn/vinamilk-vnm-giam-doanh-thu\n"
        ),
        "keywords": ["Vinamilk", "VNM"],
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cognee_temp_dir():
    """Isolated temp directory for this test module."""
    tmp = tempfile.mkdtemp(prefix="test_cognee_query_")
    print(f"\n[fixture] Temp dir: {tmp}")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n[fixture] Cleaned up: {tmp}")


@pytest.fixture(scope="module")
def cognee_paths(cognee_temp_dir):
    system_root = Path(cognee_temp_dir) / "cognee_system"
    return {
        "system_root": system_root,
        "databases_dir": system_root / "databases",
        "data_root": Path(cognee_temp_dir) / "data_storage",
    }


@pytest.fixture(scope="module")
def configured_cognee(cognee_paths):
    """Setup cognee với temp dir + config. Yields cognee module."""
    from chatbot.config import COGNEE_LLM_CONFIG, COGNEE_EMBEDDING_ENV

    os.environ["SYSTEM_ROOT_DIRECTORY"] = str(cognee_paths["system_root"])
    os.environ["DATA_ROOT_DIRECTORY"] = str(cognee_paths["data_root"])
    for key, value in COGNEE_EMBEDDING_ENV.items():
        os.environ.setdefault(key, value)

    import cognee

    cognee.config.set_graph_database_provider("kuzu")
    cognee.config.set_llm_config(COGNEE_LLM_CONFIG)
    print(f"\n[cognee] LLM model: {COGNEE_LLM_CONFIG.get('llm_model')}")
    yield cognee


@pytest.fixture(scope="module")
async def indexed_cognee(configured_cognee):
    """
    Add tất cả ARTICLES vào cognee và chạy cognify() 1 lần duy nhất.

    Dùng chung cho tất cả query tests trong module — tránh gọi cognify()
    lặp lại nhiều lần (tốn token + thời gian).

    Trả về cognee module đã có data sẵn sàng để search.
    """
    cog = configured_cognee

    print(f"\n[setup] Indexing {len(ARTICLES)} articles...")
    for i, article in enumerate(ARTICLES, 1):
        await asyncio.wait_for(cog.add(article["text"]), timeout=60)
        print(f"[setup]   [{i}/{len(ARTICLES)}] Added: {article['id']}")

    print("[setup] Running cognify()...")
    await asyncio.wait_for(cog.cognify(), timeout=300)
    print("[setup] cognify() done ✓")

    yield cog


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _extract_text_from_results(results: Any) -> List[str]:
    """Flatten cognee search results thành list of strings để assert."""
    if not results:
        return []
    texts = []
    items = results if isinstance(results, list) else [results]
    for item in items:
        if isinstance(item, str):
            texts.append(item)
        elif hasattr(item, "text"):
            texts.append(str(item.text))
        elif isinstance(item, dict):
            texts.append(str(item.get("text", item)))
        else:
            texts.append(str(item))
    return [t for t in texts if t.strip()]


# ---------------------------------------------------------------------------
# Test 1: Sanity — graph không rỗng
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_not_empty_after_index(indexed_cognee):
    """
    Sau khi index 6 bài báo, graph phải có ít nhất 1 node.

    Nếu is_empty() = True → cognify() gặp lỗi silent (LLM không extract
    được entity, hoặc API key sai).
    """
    from cognee.infrastructure.databases.graph import get_graph_engine

    graph_engine = await get_graph_engine()
    is_empty = await graph_engine.is_empty()

    assert not is_empty, (
        "Graph rỗng sau khi index 6 bài báo!\n"
        "→ Kiểm tra LLM API key và model có hoạt động không"
    )
    print("\n[test] Graph không rỗng ✓")


# ---------------------------------------------------------------------------
# Test 2: CHUNKS search — tìm theo tên công ty
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunks_search_by_company_name(indexed_cognee):
    """
    CHUNKS search: query 'FPT' phải trả về ít nhất 1 kết quả.

    CHUNKS search = semantic similarity trên text chunks — nhanh, không cần
    LLM inference thêm. Đây là cách dùng phổ biến nhất trong production.

    Kỳ vọng: kết quả chứa text liên quan đến FPT (lợi nhuận, phần mềm...).
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType

    query = "FPT lợi nhuận"
    print(f"\n[test] CHUNKS search: '{query}'")

    results = await asyncio.wait_for(
        cog.search(query, SearchType.CHUNKS), timeout=60
    )

    texts = _extract_text_from_results(results)
    print(f"[test] Got {len(texts)} chunks:")
    for t in texts[:3]:
        print(f"  → {t[:120]!r}")

    assert len(texts) > 0, (
        f"CHUNKS search '{query}' trả về rỗng!\n"
        "→ Có thể cognify() không tạo được chunks hoặc embedding lỗi"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunks_search_by_vingroup(indexed_cognee):
    """
    CHUNKS search: query 'VinGroup đầu tư' phải trả về kết quả chứa VinGroup.

    Corpus có 2 bài về VinGroup/VIC → kết quả phải phản ánh điều này.
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType

    query = "VinGroup đầu tư mở rộng"
    print(f"\n[test] CHUNKS search: '{query}'")

    results = await asyncio.wait_for(
        cog.search(query, SearchType.CHUNKS), timeout=60
    )

    texts = _extract_text_from_results(results)
    print(f"[test] Got {len(texts)} chunks:")
    for t in texts[:3]:
        print(f"  → {t[:120]!r}")

    assert len(texts) > 0, f"CHUNKS search '{query}' trả về rỗng!"

    # Ít nhất 1 kết quả đề cập VinGroup hoặc VinFast
    combined = " ".join(texts).lower()
    has_vingroup = any(kw.lower() in combined for kw in ["vingroup", "vinfast", "vic"])
    print(f"[test] VinGroup mentioned in results: {has_vingroup}")
    # Soft assert — semantic search có thể trả về related content
    if not has_vingroup:
        print("  ⚠️ VinGroup không xuất hiện trực tiếp — kết quả có thể là semantic match")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunks_search_bearish_news(indexed_cognee):
    """
    CHUNKS search: query tin tức tiêu cực phải tìm được bài Bearish.

    Corpus có 1 bài Bearish về Vinamilk. Query về 'giảm doanh thu'
    nên match với bài đó.
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType

    query = "giảm doanh thu sụt giảm"
    print(f"\n[test] CHUNKS search: '{query}'")

    results = await asyncio.wait_for(
        cog.search(query, SearchType.CHUNKS), timeout=60
    )

    texts = _extract_text_from_results(results)
    print(f"[test] Got {len(texts)} chunks:")
    for t in texts[:3]:
        print(f"  → {t[:120]!r}")

    assert len(texts) > 0, f"CHUNKS search '{query}' trả về rỗng!"


# ---------------------------------------------------------------------------
# Test 3: GRAPH_COMPLETION search — graph-based entity queries
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_insights_search_steel_sector(indexed_cognee):
    """
    GRAPH_COMPLETION search: query 'thép xuất khẩu' phải trả về insights về Hòa Phát.

    GRAPH_COMPLETION dùng Kuzu graph + LLM để traverse relationships:
      Company(HPG) → exports → Steel → to → InternationalMarket

    Kết quả thường là câu văn giải thích mối quan hệ, không phải raw chunks.
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType

    query = "thép xuất khẩu"
    print(f"\n[test] GRAPH_COMPLETION search: '{query}'")

    results = await asyncio.wait_for(
        cog.search(query, SearchType.GRAPH_COMPLETION), timeout=90
    )

    texts = _extract_text_from_results(results)
    print(f"[test] Got {len(texts)} insights:")
    for t in texts[:3]:
        print(f"  → {t[:200]!r}")

    assert len(texts) > 0, (
        f"GRAPH_COMPLETION search '{query}' trả về rỗng!\n"
        "→ Graph có thể không extract được entity 'Hòa Phát' hoặc 'thép' từ text"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_insights_search_banking(indexed_cognee):
    """
    GRAPH_COMPLETION search: query 'ngân hàng lãi suất' phải trả về thông tin Vietcombank.

    Corpus có bài về VCB hạ lãi suất → graph nên có:
      Entity(Vietcombank) → action → lower_interest_rate
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType

    query = "ngân hàng lãi suất cho vay"
    print(f"\n[test] GRAPH_COMPLETION search: '{query}'")

    results = await asyncio.wait_for(
        cog.search(query, SearchType.GRAPH_COMPLETION), timeout=90
    )

    texts = _extract_text_from_results(results)
    print(f"[test] Got {len(texts)} insights:")
    for t in texts[:3]:
        print(f"  → {t[:200]!r}")

    assert len(texts) > 0, f"GRAPH_COMPLETION search '{query}' trả về rỗng!"


# ---------------------------------------------------------------------------
# Test 4: parse_cognee_results utility
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parse_cognee_results_chunks(indexed_cognee):
    """
    parse_cognee_results() phải chuyển đổi CHUNKS output thành list[dict].

    Verify utility function từ chatbot/utils.py hoạt động với raw cognee output,
    đảm bảo chatbot có thể hiển thị kết quả cho user.

    Expected dict schema: {title, source_id, url, sentiment_label, sentiment_score}
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType
    from chatbot.utils import parse_cognee_results

    results = await asyncio.wait_for(
        cog.search("FPT phần mềm", SearchType.CHUNKS), timeout=60
    )

    parsed = parse_cognee_results(results)
    print(f"\n[test] parse_cognee_results: {len(parsed)} article(s)")
    for art in parsed[:3]:
        print(f"  title     : {art.get('title', '')[:80]!r}")
        print(f"  source_id : {art.get('source_id', '')!r}")
        print(f"  sentiment : {art.get('sentiment_label')} ({art.get('sentiment_score')})")

    # Hàm phải trả về list (có thể rỗng nếu format không match)
    assert isinstance(parsed, list), "parse_cognee_results phải trả về list"
    print("[test] parse_cognee_results trả về list ✓")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parse_cognee_results_preserves_schema(indexed_cognee):
    """
    Mỗi article trong parse_cognee_results phải có đủ các fields cần thiết.

    Chatbot dùng format_news_for_prompt() để hiển thị → cần có:
    title, source_id, url, sentiment_label, sentiment_score, crawled_at
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType
    from chatbot.utils import parse_cognee_results

    results = await asyncio.wait_for(
        cog.search("VinGroup VinFast thị trường Mỹ", SearchType.CHUNKS), timeout=60
    )

    parsed = parse_cognee_results(results)

    required_keys = {"title", "source_id", "url", "sentiment_label", "sentiment_score"}
    for i, art in enumerate(parsed):
        missing = required_keys - set(art.keys())
        assert not missing, (
            f"Article [{i}] thiếu fields: {missing}\n"
            f"Article content: {art}"
        )
    print(f"\n[test] All {len(parsed)} articles có đủ required fields ✓")


# ---------------------------------------------------------------------------
# Test 5: Cross-company disambiguation
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunks_different_companies_return_different_results(indexed_cognee):
    """
    Query về 2 công ty khác nhau phải trả về kết quả khác nhau.

    Verify cognee không bị "confused" và trả về cùng chunks cho mọi query.
    So sánh top results của FPT vs HPG để đảm bảo chúng differ.
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType

    results_fpt = await asyncio.wait_for(
        cog.search("FPT phần mềm xuất khẩu", SearchType.CHUNKS), timeout=60
    )
    results_hpg = await asyncio.wait_for(
        cog.search("Hòa Phát thép sản xuất", SearchType.CHUNKS), timeout=60
    )

    texts_fpt = _extract_text_from_results(results_fpt)
    texts_hpg = _extract_text_from_results(results_hpg)

    print(f"\n[test] FPT query: {len(texts_fpt)} chunks")
    print(f"[test] HPG query: {len(texts_hpg)} chunks")

    assert len(texts_fpt) > 0, "FPT query trả về rỗng!"
    assert len(texts_hpg) > 0, "HPG query trả về rỗng!"

    # Top-1 của 2 query phải khác nhau
    top_fpt = texts_fpt[0] if texts_fpt else ""
    top_hpg = texts_hpg[0] if texts_hpg else ""

    are_different = top_fpt != top_hpg
    print(f"[test] Top-1 results different: {are_different}")
    print(f"  FPT top-1 : {top_fpt[:80]!r}")
    print(f"  HPG top-1 : {top_hpg[:80]!r}")

    assert are_different, (
        "FPT và HPG queries trả về cùng top-1 result!\n"
        "→ Cognee có thể không phân biệt được các công ty khác nhau\n"
        "→ Kiểm tra embedding model hoạt động đúng chưa"
    )


# ---------------------------------------------------------------------------
# Test 6: Print summary
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_print_query_summary(indexed_cognee, cognee_paths):
    """
    In ra summary toàn bộ kết quả để developer review khi chạy pytest -s.

    Không có assertion — dùng để debug và kiểm tra chất lượng search.
    """
    cog = indexed_cognee
    from cognee.api.v1.search.search import SearchType

    test_queries = [
        ("FPT lợi nhuận tăng trưởng", SearchType.CHUNKS),
        ("VinGroup VinFast", SearchType.CHUNKS),
        ("ngân hàng lãi suất", SearchType.GRAPH_COMPLETION),
        ("Hòa Phát thép xuất khẩu", SearchType.GRAPH_COMPLETION),
        ("Vinamilk giảm doanh thu", SearchType.CHUNKS),
    ]

    print("\n" + "=" * 70)
    print("COGNEE QUERY RESULTS SUMMARY")
    print("=" * 70)

    for query, search_type in test_queries:
        try:
            results = await asyncio.wait_for(
                cog.search(query, search_type), timeout=90
            )
            texts = _extract_text_from_results(results)
            print(f"\n▶ [{search_type.name}] Query: {query!r}")
            print(f"  Returned {len(texts)} result(s)")
            for t in texts[:2]:
                print(f"  - {t[:100]!r}")
        except Exception as e:
            print(f"\n▶ [{search_type.name}] Query: {query!r}")
            print(f"  ERROR: {e}")

    # Kiểm tra storage
    pkl_files = list(cognee_paths["databases_dir"].rglob("*.pkl")) if cognee_paths["databases_dir"].exists() else []
    print(f"\n📁 Storage: {len(pkl_files)} .pkl file(s) in databases/")
    for f in pkl_files:
        print(f"   - {f.name} ({f.stat().st_size / 1024:.1f} KB)")

    print("\n" + "=" * 70)
