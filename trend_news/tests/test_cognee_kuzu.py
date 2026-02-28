"""
Integration Test: Cognee + Kuzu Graph Database Storage
=======================================================

Mục đích: Verify cách Cognee 0.5.x lưu trữ Kuzu graph database để developer
hiểu rõ cấu trúc file system sau khi index dữ liệu.

Kiến thức nền:
--------------
Cognee 0.5.x KHÔNG dùng folder `kuzu/` native mà serialize toàn bộ graph
vào file `.pkl` (pickle format với KUZU header) để dễ transport và backup.

Cấu trúc thực tế sau khi cognify():
    output/cognee_db/
    ├── databases/
    │   └── {user_uuid}/
    │       └── {dataset_uuid}.pkl   ← Kuzu graph DB (serialized, ~50-500KB)
    ├── data_storage/                 ← Raw text files được add vào
    └── kuzu/                         ← RỖNG trong v0.5.x (legacy placeholder)

File .pkl chứa:
    - 4 bytes đầu: magic bytes "KUZU" (0x4b555a55)
    - Phần còn lại: serialized graph data (nodes, edges, properties)

Chạy test (từ thư mục trend_news/):
    pytest tests/test_cognee_kuzu.py -v -m integration
    pytest tests/test_cognee_kuzu.py -v -s          # thấy print output

Yêu cầu:
    - OPENAI_API_KEY hoặc GEMINI_API_KEY trong .env
    - pip install cognee kuzu fastembed pytest pytest-asyncio
"""

import asyncio
import os
import sys
import shutil
import tempfile
from pathlib import Path
from typing import List

import pytest

# ---------------------------------------------------------------------------
# Path setup — đảm bảo có thể import chatbot.config
# ---------------------------------------------------------------------------
_TREND_NEWS_DIR = Path(__file__).parent.parent
if str(_TREND_NEWS_DIR) not in sys.path:
    sys.path.insert(0, str(_TREND_NEWS_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cognee_temp_dir():
    """
    Tạo temp directory riêng biệt cho toàn bộ test module.
    Đảm bảo tests không ảnh hưởng đến cognee_db thật trong output/.

    Scope=module để cognee chỉ khởi tạo 1 lần (tránh conflict giữa tests).
    """
    tmp = tempfile.mkdtemp(prefix="test_cognee_kuzu_")
    print(f"\n[fixture] Temp dir: {tmp}")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n[fixture] Cleaned up: {tmp}")


@pytest.fixture(scope="module")
def cognee_paths(cognee_temp_dir):
    """
    Trả về dict các path quan trọng trong cognee DB directory.

    Cấu trúc:
        system_root/
        ├── databases/          ← .pkl files nằm ở đây
        └── kuzu/               ← legacy, phải rỗng
        data_root/              ← raw text files
    """
    system_root = Path(cognee_temp_dir) / "cognee_system"
    return {
        "system_root": system_root,
        "databases_dir": system_root / "databases",
        "kuzu_dir": system_root / "kuzu",
        "data_root": Path(cognee_temp_dir) / "data_storage",
    }


@pytest.fixture(scope="module")
def configured_cognee(cognee_paths):
    """
    Setup cognee với temp directory và config từ chatbot.config.

    QUAN TRỌNG: Phải set env vars TRƯỚC KHI import cognee vì cognee dùng
    pydantic-settings — đọc config tại class instantiation time.

    Yields cognee module đã configured, sẵn sàng dùng trong tests.
    """
    from chatbot.config import COGNEE_LLM_CONFIG, COGNEE_EMBEDDING_ENV

    # Set paths TRƯỚC khi import cognee
    os.environ["SYSTEM_ROOT_DIRECTORY"] = str(cognee_paths["system_root"])
    os.environ["DATA_ROOT_DIRECTORY"] = str(cognee_paths["data_root"])

    # Set embedding env vars (fastembed, không cần API key)
    for key, value in COGNEE_EMBEDDING_ENV.items():
        os.environ.setdefault(key, value)

    import cognee

    cognee.config.set_graph_database_provider("kuzu")
    cognee.config.set_llm_config(COGNEE_LLM_CONFIG)

    print(f"\n[cognee] LLM model: {COGNEE_LLM_CONFIG.get('llm_model')}")
    print(f"[cognee] Embedding: {os.environ.get('EMBEDDING_MODEL')}")

    yield cognee


# ---------------------------------------------------------------------------
# Fixture: pre-populate graph (1 lần cho cả module)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def populated_graph(configured_cognee, cognee_paths):
    """
    Add 3 bài báo tài chính vào cognee và chạy cognify() 1 lần.

    Đây là integration step tốn thời gian nhất (~30-90s tùy LLM latency).
    Các test sau sẽ dùng chung graph này thay vì gọi cognify() lại.

    Nội dung test mô phỏng format thật từ indexer._format_article():
        TIN TỨC TÀI CHÍNH: [source] YYYY-MM-DD
        Tiêu đề: ...
        Cảm xúc thị trường: Bullish (+0.85)
    """
    cog = configured_cognee
    articles = [
        (
            "TIN TỨC TÀI CHÍNH: [vnexpress] 2026-02-28\n"
            "Tiêu đề: VinGroup đầu tư 1 tỷ USD vào VinFast mở rộng thị trường Mỹ\n"
            "Cảm xúc thị trường: Bullish (+0.85)\n"
            "Nguồn: https://vnexpress.net/vingroup-vinfast\n"
        ),
        (
            "TIN TỨC TÀI CHÍNH: [cafef] 2026-02-28\n"
            "Tiêu đề: Cổ phiếu VIC tăng 5% sau thông báo kế hoạch mở rộng\n"
            "Cảm xúc thị trường: Bullish (+0.72)\n"
            "Nguồn: https://cafef.vn/co-phieu-vic\n"
        ),
        (
            "TIN TỨC TÀI CHÍNH: [vietstock] 2026-02-28\n"
            "Tiêu đề: FPT công bố lợi nhuận quý 4/2025 tăng 32% so với cùng kỳ\n"
            "Cảm xúc thị trường: Bullish (+0.91)\n"
            "Nguồn: https://vietstock.vn/fpt-q4-2025\n"
        ),
    ]

    print(f"\n[populate] Adding {len(articles)} articles to cognee...")
    for i, text in enumerate(articles, 1):
        await asyncio.wait_for(cog.add(text), timeout=60)
        print(f"[populate]   [{i}/{len(articles)}] Added ✓")

    print("[populate] Running cognify() — this calls the LLM API...")
    await asyncio.wait_for(cog.cognify(), timeout=180)
    print("[populate] cognify() complete ✓")

    yield cognee_paths


# ---------------------------------------------------------------------------
# Tests: Cấu trúc file system
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_databases_directory_exists(populated_graph):
    """
    Sau cognify(), Cognee phải tạo folder databases/ trong system_root.

    Đây là nơi chứa toàn bộ Kuzu graph data dưới dạng .pkl files.
    Nếu folder này không tồn tại → cognify() bị lỗi hoặc chưa chạy đúng.
    """
    paths = populated_graph
    databases_dir = paths["databases_dir"]

    assert databases_dir.exists(), (
        f"databases/ không tồn tại tại {databases_dir}\n"
        "→ cognify() có thể đã fail hoặc SYSTEM_ROOT_DIRECTORY sai"
    )
    print(f"\n[test] databases/ tồn tại: {databases_dir}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pkl_files_created(populated_graph):
    """
    Cognee 0.5.x phải tạo ít nhất 1 file .pkl trong databases/.

    Cấu trúc: databases/{user_uuid}/{dataset_uuid}.pkl
    - user_uuid: UUID của user (default user trong cognee)
    - dataset_uuid: UUID của dataset được index

    Không giống Cognee cũ dùng native Kuzu folder,
    v0.5.x serialize toàn bộ graph vào 1 file pickle duy nhất.
    """
    paths = populated_graph
    databases_dir = paths["databases_dir"]

    pkl_files: List[Path] = list(databases_dir.rglob("*.pkl"))
    assert len(pkl_files) > 0, (
        f"Không tìm thấy file .pkl nào trong {databases_dir}\n"
        "→ Cognee có thể đang dùng version khác hoặc graph provider khác"
    )

    print(f"\n[test] Tìm thấy {len(pkl_files)} file(s) .pkl:")
    for f in pkl_files:
        size_kb = f.stat().st_size / 1024
        rel = f.relative_to(databases_dir)
        print(f"  - {rel}  ({size_kb:.1f} KB)")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pkl_file_size_reasonable(populated_graph):
    """
    File .pkl phải có kích thước > 1KB — xác nhận graph thật sự có data.

    Nếu file < 1KB → graph rỗng hoặc cognify() không extract được entity nào.
    Nếu file > 10MB → bất thường, có thể leak data hoặc lỗi serialization.
    """
    paths = populated_graph
    databases_dir = paths["databases_dir"]
    pkl_files = list(databases_dir.rglob("*.pkl"))

    assert pkl_files, "Không có .pkl file để kiểm tra size"

    for pkl_file in pkl_files:
        size_bytes = pkl_file.stat().st_size
        size_kb = size_bytes / 1024
        assert size_bytes > 1024, (
            f"{pkl_file.name}: {size_kb:.1f} KB — quá nhỏ, graph có thể rỗng"
        )
        print(f"\n[test] {pkl_file.name}: {size_kb:.1f} KB ✓")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pkl_has_kuzu_magic_bytes(populated_graph):
    """
    File .pkl của Cognee KHÔNG phải Python pickle thông thường.
    Nó là Kuzu database được serialized với header đặc biệt.

    4 bytes đầu tiên phải là: 0x4b 0x55 0x5a 0x55 = "KUZU"

    Cách verify thủ công:
        $ xxd file.pkl | head -1
        00000000: 4b55 5a55 2700 0000...   KUZU'...

        $ python -c "
        with open('file.pkl', 'rb') as f:
            print(f.read(4))  # b'KUZU'
        "
    """
    paths = populated_graph
    databases_dir = paths["databases_dir"]
    pkl_files = list(databases_dir.rglob("*.pkl"))

    assert pkl_files, "Không có .pkl file để kiểm tra magic bytes"

    KUZU_MAGIC = b"KUZU"
    print()
    for pkl_file in pkl_files:
        with open(pkl_file, "rb") as f:
            header = f.read(4)

        hex_header = header.hex()
        print(f"[test] {pkl_file.name}: header = {hex_header} ({header})")

        assert header == KUZU_MAGIC, (
            f"{pkl_file.name}: magic bytes sai!\n"
            f"  Expected: {KUZU_MAGIC.hex()} (KUZU)\n"
            f"  Got:      {hex_header}\n"
            "→ File có thể bị corrupt hoặc Cognee version đã thay đổi format"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kuzu_legacy_folder_is_empty(populated_graph):
    """
    Folder kuzu/ trong system_root là legacy từ Cognee < 0.5.x.

    Trong Cognee 0.5.x, folder này KHÔNG được dùng để lưu graph data.
    Nếu nó tồn tại thì phải rỗng.

    Nếu folder này có data → có thể đang chạy Cognee version cũ.
    """
    paths = populated_graph
    kuzu_dir = paths["kuzu_dir"]

    if not kuzu_dir.exists():
        print(f"\n[test] kuzu/ không tồn tại (expected trong v0.5.x) ✓")
        return

    all_files = list(kuzu_dir.rglob("*"))
    actual_files = [f for f in all_files if f.is_file()]

    print(f"\n[test] kuzu/ tồn tại nhưng {'rỗng' if not actual_files else 'có files!'}")
    if actual_files:
        for f in actual_files[:5]:
            print(f"  - {f.relative_to(kuzu_dir)}")

    assert len(actual_files) == 0, (
        f"kuzu/ có {len(actual_files)} file(s) — Cognee đang dùng native Kuzu format?\n"
        "→ Kiểm tra lại cognee version: pip show cognee"
    )


# ---------------------------------------------------------------------------
# Tests: Graph engine API
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_not_empty_after_cognify(populated_graph):
    """
    Verify qua Cognee's graph engine API rằng graph thật sự có nodes.

    Dùng get_graph_engine() → is_empty() để kiểm tra.
    Đây là cách programmatic để verify graph data, không phụ thuộc file system.

    Nếu is_empty() = True sau cognify() → LLM không extract được entity nào
    từ text, hoặc cognify() bị lỗi silent.
    """
    _ = populated_graph  # ordering: ensures cognify() ran before this test

    from cognee.infrastructure.databases.graph import get_graph_engine

    graph_engine = await get_graph_engine()
    is_empty = await graph_engine.is_empty()

    assert not is_empty, (
        "Graph rỗng sau cognify()!\n"
        "→ LLM có thể không extract được entity từ text tiếng Việt\n"
        "→ Kiểm tra LLM API key và model có hỗ trợ Vietnamese không"
    )
    print("\n[test] Graph không rỗng sau cognify() ✓")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_data_storage_has_raw_files(populated_graph):
    """
    Ngoài .pkl graph, Cognee còn lưu raw text trong data_storage/.

    Mỗi lần gọi cognee.add(text) → tạo 1 file text trong data_storage/.
    Đây là nguồn dữ liệu gốc trước khi được cognify() xử lý thành graph.

    Structure:
        data_storage/
        └── {dataset_name}/
            └── {file_uuid}.txt  (hoặc .html, .pdf tùy loại data)
    """
    paths = populated_graph
    data_root = paths["data_root"]

    if not data_root.exists():
        pytest.skip("data_storage/ không tồn tại — có thể cognee version khác")

    all_files = list(data_root.rglob("*"))
    actual_files = [f for f in all_files if f.is_file()]

    print(f"\n[test] data_storage/ có {len(actual_files)} raw file(s):")
    for f in actual_files[:5]:
        size_b = f.stat().st_size
        print(f"  - {f.relative_to(data_root)} ({size_b} bytes)")

    assert len(actual_files) > 0, (
        "Không có raw file nào trong data_storage/\n"
        "→ cognee.add() có thể bị lỗi"
    )


# ---------------------------------------------------------------------------
# Utility test: in ra toàn bộ structure cho developer
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_print_full_storage_structure(populated_graph):
    """
    Không phải assertion — print toàn bộ cấu trúc file system để developer
    có thể xem bằng `pytest -s`.

    Output mẫu:
        cognee_system/
        ├── databases/
        │   └── a1b2c3d4-xxxx/
        │       └── e5f6g7h8-yyyy.pkl  (142.3 KB)
        └── kuzu/  (empty — legacy)

        data_storage/
        └── main_dataset/
            ├── uuid1.txt  (412 bytes)
            ├── uuid2.txt  (398 bytes)
            └── uuid3.txt  (445 bytes)
    """
    paths = populated_graph
    system_root = paths["system_root"]
    data_root = paths["data_root"]

    def _print_tree(root: Path, indent: str = ""):
        if not root.exists():
            print(f"{indent}[không tồn tại]")
            return
        entries = sorted(root.iterdir())
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            if entry.is_dir():
                print(f"{indent}{connector}{entry.name}/")
                child_indent = indent + ("    " if i == len(entries) - 1 else "│   ")
                _print_tree(entry, child_indent)
            else:
                size_kb = entry.stat().st_size / 1024
                print(f"{indent}{connector}{entry.name}  ({size_kb:.1f} KB)")

    print("\n" + "=" * 60)
    print("COGNEE STORAGE STRUCTURE")
    print("=" * 60)

    print(f"\n{system_root.name}/")
    _print_tree(system_root, "")

    if data_root.exists():
        print(f"\n{data_root.name}/")
        _print_tree(data_root, "")

    print("\n" + "=" * 60)
    print("KEY FACTS về Cognee 0.5.x + Kuzu:")
    print("  • Graph DB format  : Pickle với KUZU header (0x4b555a55)")
    print("  • Graph DB location: databases/{user_uuid}/{dataset_uuid}.pkl")
    print("  • Raw data location: data_storage/ (text files)")
    print("  • kuzu/ folder     : RỖNG (legacy, không dùng trong v0.5.x)")
    print("  • Verify magic bytes: xxd file.pkl | head -1")
    print("=" * 60)
