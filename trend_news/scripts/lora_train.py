"""
LoRA fine-tuning for CN/EN financial sentiment.

Architecture:
  Base model: Erlangshen-Roberta-110M-Sentiment (CN) or ProsusAI/finbert (EN)
  Adapter:    LoRA rank=8, alpha=16, target=query+value
  Training:   CPU-only, FP32 (M1 compatible), gradient checkpointing

M1 performance estimate:
  110M model, rank-8 LoRA → only 0.5% params trainable (~550K params)
  128 batch steps × 500 samples ≈ ~5-10 min on M1 CPU per epoch

Usage:
  # Build corpus first
  python scripts/build_corpus.py

  # Train CN model
  python scripts/lora_train.py --lang cn --epochs 3

  # Train EN model
  python scripts/lora_train.py --lang en --epochs 3

  # Evaluate
  python scripts/lora_train.py --lang cn --eval-only

Output:
  models/lora_cn/   (LoRA adapter weights, ~8MB)
  models/lora_en/   (LoRA adapter weights, ~8MB)
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import (
    LoraConfig,
    TaskType,
    get_peft_model,
    PeftModel,
)
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
)

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Config ────────────────────────────────────────────────────────────────────

MODELS = {
    "cn": "IDEA-CCNL/Erlangshen-Roberta-110M-Sentiment",
    "en": "ProsusAI/finbert",
}

CORPUS_DIR  = Path("data/corpus")
MODELS_DIR  = Path("models")

# LoRA hyperparams (tuned for M1 CPU efficiency)
LORA_RANK      = 8
LORA_ALPHA     = 16
LORA_DROPOUT   = 0.05
LORA_TARGETS   = ["query", "value"]   # Roberta/BERT attention

# Training
BATCH_SIZE     = 16
LEARNING_RATE  = 2e-4
MAX_EPOCHS     = 3
MAX_LENGTH     = 128
WARMUP_STEPS   = 50
EVAL_STEPS     = 50

LABEL2ID = {"positive": 0, "negative": 1, "neutral": 2}
ID2LABEL = {0: "positive", 1: "negative", 2: "neutral"}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def make_dataset(tokenizer, samples: list[dict], max_length: int = MAX_LENGTH) -> Dataset:
    texts  = [s["text"] for s in samples]
    labels = [LABEL2ID.get(s["label"], 2) for s in samples]

    enc = tokenizer(
        texts,
        truncation=True,
        max_length=max_length,
        padding="max_length",
        return_tensors="pt",
    )
    enc["labels"] = torch.tensor(labels, dtype=torch.long)
    return Dataset.from_dict({k: v.tolist() for k, v in enc.items()})


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(model, dataset: Dataset, batch_size: int = 32, device="cpu") -> dict:
    model.eval()
    all_preds, all_labels = [], []

    for i in range(0, len(dataset), batch_size):
        batch = dataset[i: i + batch_size]
        input_ids = torch.tensor(batch["input_ids"]).to(device)
        attention_mask = torch.tensor(batch["attention_mask"]).to(device)
        labels = torch.tensor(batch["labels"])

        with torch.no_grad():
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        preds = outputs.logits.argmax(-1).cpu()
        all_preds.extend(preds.tolist())
        all_labels.extend(labels.tolist())

    correct = sum(p == l for p, l in zip(all_preds, all_labels))
    acc = correct / len(all_labels) if all_labels else 0.0

    # Per-class metrics
    per_class = {}
    for cls_id, cls_name in ID2LABEL.items():
        tp = sum(1 for p, l in zip(all_preds, all_labels) if p == cls_id and l == cls_id)
        fp = sum(1 for p, l in zip(all_preds, all_labels) if p == cls_id and l != cls_id)
        fn = sum(1 for p, l in zip(all_preds, all_labels) if p != cls_id and l == cls_id)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[cls_name] = {"precision": round(precision,3), "recall": round(recall,3), "f1": round(f1,3)}

    return {"accuracy": round(acc, 4), "per_class": per_class, "total": len(all_labels)}


# ── Training loop ─────────────────────────────────────────────────────────────

def train(lang: str, epochs: int = MAX_EPOCHS, resume: bool = False):
    model_name = MODELS[lang]
    out_dir    = MODELS_DIR / f"lora_{lang}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"LoRA Fine-tuning: {lang.upper()} financial sentiment")
    print(f"Base model: {model_name}")
    print(f"LoRA: rank={LORA_RANK}, alpha={LORA_ALPHA}, targets={LORA_TARGETS}")
    print(f"Epochs: {epochs}, LR: {LEARNING_RATE}, batch: {BATCH_SIZE}")
    print(f"{'='*60}\n")

    device = "cpu"
    # M1 MPS check
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        device = "mps"
        print("  🍎 Using Apple MPS (M1/M2 GPU)")
    else:
        print("  💻 Using CPU (MPS unavailable)")

    # Load tokenizer + model
    print("  Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    print("  Loading base model...")
    base_model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=3,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True,
    )

    # Apply LoRA
    lora_config = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=LORA_TARGETS,
        bias="none",
    )
    model = get_peft_model(base_model, lora_config)
    model.to(device)

    trainable, total = model.get_nb_trainable_parameters()
    print(f"  Trainable params: {trainable:,} / {total:,} ({100*trainable/total:.1f}%)")

    # Load data
    train_samples = load_jsonl(CORPUS_DIR / f"{lang}_train.jsonl")
    val_samples   = load_jsonl(CORPUS_DIR / f"{lang}_val.jsonl")
    test_samples  = load_jsonl(CORPUS_DIR / f"{lang}_test.jsonl")

    if not train_samples:
        print(f"  ❌ No training data found at {CORPUS_DIR}/{lang}_train.jsonl")
        print("  Run: python scripts/build_corpus.py first")
        return

    print(f"\n  Data: train={len(train_samples)}, val={len(val_samples)}, test={len(test_samples)}")

    train_ds = make_dataset(tokenizer, train_samples)
    val_ds   = make_dataset(tokenizer, val_samples)
    test_ds  = make_dataset(tokenizer, test_samples)

    # Optimizer
    optimizer = AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
    total_steps = (len(train_samples) // BATCH_SIZE) * epochs
    scheduler = CosineAnnealingLR(optimizer, T_max=total_steps)

    # Training loop
    best_val_acc = 0.0
    step = 0

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        epoch_start = time.time()
        indices = list(range(len(train_ds)))

        # Shuffle
        import random; random.shuffle(indices)

        for i in range(0, len(indices), BATCH_SIZE):
            batch_idx = indices[i: i + BATCH_SIZE]
            batch = train_ds[batch_idx]

            input_ids      = torch.tensor(batch["input_ids"]).to(device)
            attention_mask = torch.tensor(batch["attention_mask"]).to(device)
            labels         = torch.tensor(batch["labels"]).to(device)

            optimizer.zero_grad()
            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()
            step += 1

            if step % EVAL_STEPS == 0:
                val_metrics = evaluate(model, val_ds, device=device)
                print(f"  step={step:4d} loss={epoch_loss/(i//BATCH_SIZE+1):.4f} "
                      f"val_acc={val_metrics['accuracy']:.3f}")

        epoch_time = time.time() - epoch_start
        val_metrics = evaluate(model, val_ds, device=device)
        val_acc = val_metrics["accuracy"]

        print(f"\n  ── Epoch {epoch+1}/{epochs} "
              f"loss={epoch_loss/(len(indices)//BATCH_SIZE+1):.4f} "
              f"val_acc={val_acc:.3f} "
              f"time={epoch_time:.0f}s")

        for cls, m in val_metrics["per_class"].items():
            print(f"    {cls:10s}: P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f}")

        # Save best
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            model.save_pretrained(out_dir / "best")
            tokenizer.save_pretrained(out_dir / "best")
            print(f"  ✅ Saved best model (val_acc={val_acc:.3f})")

    # Final eval on test
    print("\n  Final test evaluation...")
    test_metrics = evaluate(model, test_ds, device=device)
    print(f"  Test accuracy: {test_metrics['accuracy']:.3f}")
    for cls, m in test_metrics["per_class"].items():
        print(f"    {cls:10s}: P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f}")

    # Save results
    results = {
        "lang": lang, "model": model_name,
        "best_val_acc": best_val_acc,
        "test_metrics": test_metrics,
        "train_samples": len(train_samples),
        "epochs": epochs,
    }
    with open(out_dir / "train_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✅ Training complete → {out_dir}/")
    return results


# ── Eval-only mode ────────────────────────────────────────────────────────────

def eval_only(lang: str):
    model_name = MODELS[lang]
    adapter_dir = MODELS_DIR / f"lora_{lang}" / "best"

    if not adapter_dir.exists():
        print(f"  ❌ No trained adapter found at {adapter_dir}")
        return

    print(f"\nEvaluating {lang.upper()} LoRA adapter...")
    tokenizer = AutoTokenizer.from_pretrained(adapter_dir)
    base_model = AutoModelForSequenceClassification.from_pretrained(
        model_name, num_labels=3, id2label=ID2LABEL, label2id=LABEL2ID,
        ignore_mismatched_sizes=True
    )
    model = PeftModel.from_pretrained(base_model, adapter_dir)
    model.eval()

    test_samples = load_jsonl(CORPUS_DIR / f"{lang}_test.jsonl")
    if not test_samples:
        print("  No test data found")
        return

    test_ds = make_dataset(tokenizer, test_samples)
    metrics = evaluate(model, test_ds)
    print(f"Test accuracy: {metrics['accuracy']:.3f}")
    for cls, m in metrics["per_class"].items():
        print(f"  {cls:10s}: P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["cn", "en"], required=True)
    parser.add_argument("--epochs", type=int, default=MAX_EPOCHS)
    parser.add_argument("--eval-only", action="store_true")
    args = parser.parse_args()

    if args.eval_only:
        eval_only(args.lang)
    else:
        train(args.lang, epochs=args.epochs)
