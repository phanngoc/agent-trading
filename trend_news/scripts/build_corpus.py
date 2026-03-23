"""
Build labeled corpus for LoRA fine-tuning from trend_news.db.

Steps:
  1. Extract CN/EN articles with strong lexicon signal (Phase 1 auto-label)
  2. Run neural models as silver labels (cross-validate vs lexicon)
  3. Merge + deduplicate → train/val/test split
  4. Export to JSONL for training

Usage:
  python scripts/build_corpus.py [--output data/corpus] [--min-conf 0.65]

Output:
  data/corpus/cn_train.jsonl   (CN financial articles → pos/neg/neu)
  data/corpus/en_train.jsonl   (EN financial articles → pos/neg/neu)
  data/corpus/stats.json       (corpus stats)
"""
import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH   = Path("output/trend_news.db")
OUT_DIR   = Path("data/corpus")
SEED      = 42

# Lexicon strong threshold → use as silver label directly
LEXICON_STRONG = 0.25

# Neural confidence threshold to use as label
NEURAL_CONF_THRESHOLD = 0.72

# Label distribution: cap neutral at 2× minority to prevent imbalance
MAX_NEUTRAL_RATIO = 2.0

CN_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# ── Label mapping ─────────────────────────────────────────────────────────────

def score_to_label(score: float) -> str:
    if score >= 0.20:
        return "positive"
    elif score <= -0.20:
        return "negative"
    return "neutral"


# ── Phase 1: Lexicon-labeled samples ─────────────────────────────────────────

def extract_lexicon_labeled(db_path: Path) -> tuple[list, list]:
    """
    Extract articles where lexicon already has strong signal.
    Returns (cn_samples, en_samples) as list of {"text", "label"}.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    cn_samples, en_samples = [], []

    # CN: titles with Chinese characters + strong |score|
    c.execute("""
        SELECT title, sentiment_score FROM news_articles
        WHERE sentiment_score IS NOT NULL
        AND abs(sentiment_score) >= ?
        ORDER BY abs(sentiment_score) DESC
    """, (LEXICON_STRONG,))

    for title, score in c.fetchall():
        if not title or len(title) < 5:
            continue
        if CN_RE.search(title):
            cn_samples.append({"text": title.strip(), "label": score_to_label(score), "source": "lexicon"})
        else:
            en_samples.append({"text": title.strip(), "label": score_to_label(score), "source": "lexicon"})

    conn.close()
    print(f"  Lexicon CN: {len(cn_samples)}, EN: {len(en_samples)}")
    return cn_samples, en_samples


# ── Phase 2: Neural silver labels for unlabeled / weak-signal ────────────────

def extract_neural_labeled(db_path: Path, existing_cn: list, existing_en: list) -> tuple[list, list]:
    """
    Run neural models on articles without strong lexicon signal.
    Returns additional (cn_samples, en_samples).
    """
    try:
        from src.utils.neural_sentiment import neural_engine, _cn_model, _en_model
    except ImportError:
        print("  ⚠ Neural models unavailable, skipping phase 2")
        return [], []

    if not _cn_model.is_available() or not _en_model.is_available():
        print("  ⚠ Models not loaded")
        return [], []

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Get articles with weak/no signal
    c.execute("""
        SELECT title FROM news_articles
        WHERE abs(COALESCE(sentiment_score, 0)) < ?
        ORDER BY RANDOM()
        LIMIT 5000
    """, (LEXICON_STRONG,))

    all_titles = [r[0] for r in c.fetchall() if r[0] and len(r[0]) >= 5]
    conn.close()

    # Split by language
    cn_titles = [t for t in all_titles if CN_RE.search(t)][:2000]
    en_titles = [t for t in all_titles if not CN_RE.search(t) and all(ord(c) < 256 for c in t)][:1000]

    existing_cn_texts = {s["text"] for s in existing_cn}
    existing_en_texts = {s["text"] for s in existing_en}

    new_cn, new_en = [], []

    # Batch score CN
    if cn_titles:
        print(f"  Neural scoring {len(cn_titles)} CN articles...")
        BATCH = 32
        for i in range(0, len(cn_titles), BATCH):
            batch = cn_titles[i:i+BATCH]
            results = _cn_model.predict(batch, batch_size=BATCH)
            for text, (score, label, conf) in zip(batch, results):
                if conf >= NEURAL_CONF_THRESHOLD and text not in existing_cn_texts:
                    new_cn.append({
                        "text": text.strip(),
                        "label": "positive" if score > 0 else ("negative" if score < 0 else "neutral"),
                        "source": f"neural_cn:{conf:.2f}",
                    })

    # Batch score EN (only finance-domain)
    if en_titles:
        from src.utils.neural_sentiment import _EN_FIN_RE
        fin_en = [t for t in en_titles if _EN_FIN_RE.search(t)]
        print(f"  Neural scoring {len(fin_en)} EN financial articles...")
        BATCH = 32
        for i in range(0, len(fin_en), BATCH):
            batch = fin_en[i:i+BATCH]
            results = _en_model.predict(batch, batch_size=BATCH)
            for text, (score, label, conf) in zip(batch, results):
                if conf >= NEURAL_CONF_THRESHOLD and text not in existing_en_texts:
                    new_en.append({
                        "text": text.strip(),
                        "label": "positive" if score > 0 else ("negative" if score < 0 else "neutral"),
                        "source": f"neural_en:{conf:.2f}",
                    })

    print(f"  Neural new CN: {len(new_cn)}, new EN: {len(new_en)}")
    return new_cn, new_en


# ── Phase 3: Balance + split ──────────────────────────────────────────────────

def balance_and_split(samples: list, name: str) -> tuple[list, list, list]:
    """
    Balance classes (cap neutral) + split 80/10/10 train/val/test.
    Returns (train, val, test).
    """
    random.seed(SEED)

    pos = [s for s in samples if s["label"] == "positive"]
    neg = [s for s in samples if s["label"] == "negative"]
    neu = [s for s in samples if s["label"] == "neutral"]

    # Deduplicate by text
    def dedup(lst):
        seen = set()
        out = []
        for s in lst:
            if s["text"] not in seen:
                seen.add(s["text"])
                out.append(s)
        return out

    pos, neg, neu = dedup(pos), dedup(neg), dedup(neu)

    minority = min(len(pos), len(neg))
    max_neu = int(minority * MAX_NEUTRAL_RATIO)

    # Downsample neutral if too large
    if len(neu) > max_neu:
        random.shuffle(neu)
        neu = neu[:max_neu]

    # Upsample minority if needed (within 2x)
    if len(pos) < len(neg) // 2:
        pos = pos * (len(neg) // max(1, len(pos)) + 1)
        pos = pos[:len(neg)]
    elif len(neg) < len(pos) // 2:
        neg = neg * (len(pos) // max(1, len(neg)) + 1)
        neg = neg[:len(pos)]

    all_samples = pos + neg + neu
    random.shuffle(all_samples)

    n = len(all_samples)
    train_end = int(n * 0.80)
    val_end   = int(n * 0.90)

    train = all_samples[:train_end]
    val   = all_samples[train_end:val_end]
    test  = all_samples[val_end:]

    print(f"\n  [{name}] Total: {n} → train={len(train)}, val={len(val)}, test={len(test)}")
    print(f"    pos={len(pos)}, neg={len(neg)}, neu={len(neu)}")

    return train, val, test


# ── Phase 4: Export ───────────────────────────────────────────────────────────

def export_jsonl(samples: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"  Exported {len(samples)} samples → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUT_DIR))
    parser.add_argument("--min-conf", type=float, default=NEURAL_CONF_THRESHOLD)
    parser.add_argument("--skip-neural", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output)
    import scripts.build_corpus as _self
    _self.NEURAL_CONF_THRESHOLD = args.min_conf

    print(f"\n{'='*60}")
    print("TrendRadar Corpus Builder v1.0")
    print(f"DB: {DB_PATH}")
    print(f"Output: {out_dir}")
    print(f"{'='*60}\n")

    # Phase 1: Lexicon
    print("Phase 1: Extracting lexicon-labeled samples...")
    cn_lex, en_lex = extract_lexicon_labeled(DB_PATH)

    # Phase 2: Neural silver labels
    if not args.skip_neural:
        print("\nPhase 2: Neural silver labeling...")
        cn_neu, en_neu = extract_neural_labeled(DB_PATH, cn_lex, en_lex)
        cn_all = cn_lex + cn_neu
        en_all = en_lex + en_neu
    else:
        cn_all, en_all = cn_lex, en_lex

    # Phase 3: Balance + split
    print("\nPhase 3: Balancing + splitting...")
    cn_train, cn_val, cn_test = balance_and_split(cn_all, "CN")
    en_train, en_val, en_test = balance_and_split(en_all, "EN")

    # Phase 4: Export
    print("\nPhase 4: Exporting...")
    for lang, train, val, test in [("cn", cn_train, cn_val, cn_test),
                                    ("en", en_train, en_val, en_test)]:
        export_jsonl(train, out_dir / f"{lang}_train.jsonl")
        export_jsonl(val,   out_dir / f"{lang}_val.jsonl")
        export_jsonl(test,  out_dir / f"{lang}_test.jsonl")

    # Stats
    stats = {
        "cn": {"train": len(cn_train), "val": len(cn_val), "test": len(cn_test)},
        "en": {"train": len(en_train), "val": len(en_val), "test": len(en_test)},
    }
    with open(out_dir / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\n✅ Corpus built → {out_dir}/")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
