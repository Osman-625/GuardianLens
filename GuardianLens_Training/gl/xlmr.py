"""Methodology signal T: XLM-RoBERTa fine-tune on title + description (GPU / Colab T4).

Out-of-fold protocol (so T can be fused honestly):
  * 5 group-safe folds, identical to every other signal. For each fold, a model is fine-tuned on the other
    4 folds with class-weighted cross-entropy, linear warm-up/decay, and early stopping on an INNER group-safe
    slice (12%) of that training part. The held-out fold is never used for stopping, so its predictions are
    genuinely out-of-fold.
  * Validation (and later test) scores are the mean of the 5 fold models' probabilities.
  * Fold models are saved (fp16) under runs/<run>/xlmr/fold<k>/ and a fold that finished is skipped on re-run,
    so a dropped Colab session resumes where it stopped.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from .models import fold_indices


def _texts(df: pd.DataFrame) -> list[str]:
    return (df["title"].fillna("") + "\n" + df["description"].fillna("")).tolist()


def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _tokenizer(tc: dict, ckpt: str | None = None):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(ckpt or ("xlm-roberta-base" if tc.get("tiny") else tc["model"]))


def _new_model(tc: dict, tok):
    from transformers import AutoModelForSequenceClassification, XLMRobertaConfig
    if tc.get("tiny"):
        conf = XLMRobertaConfig(vocab_size=len(tok), hidden_size=32, num_hidden_layers=2, num_attention_heads=2,
                                intermediate_size=64, num_labels=2, pad_token_id=tok.pad_token_id)
        return AutoModelForSequenceClassification.from_config(conf)
    return AutoModelForSequenceClassification.from_pretrained(tc["model"], num_labels=2)


def _scores(model, tok, texts, max_len, bs, dev) -> np.ndarray:
    import torch
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), bs):
            b = tok(texts[i:i + bs], padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(dev)
            out.append(torch.softmax(model(**b).logits.float(), dim=-1)[:, 1].cpu().numpy())
    return np.concatenate(out) if out else np.zeros(0)


def _fit_one(tc: dict, tok, ttr, ytr, tes, yes, seed: int, dev: str, log) -> tuple[object, list[dict]]:
    """Fine-tune one model; returns it with its best-inner-AUC weights loaded, plus the epoch history."""
    import torch
    from transformers import get_linear_schedule_with_warmup

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = _new_model(tc, tok).to(dev)
    bs, ml = tc["batch_size"], tc["max_length"]
    total = int(np.ceil(len(ttr) / bs)) * tc["epochs"]
    no_decay = ("bias", "LayerNorm.weight")
    groups = [
        {"params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)], "weight_decay": tc["weight_decay"]},
        {"params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], "weight_decay": 0.0},
    ]
    opt = torch.optim.AdamW(groups, lr=tc["learning_rate"])
    sched = get_linear_schedule_with_warmup(opt, int(total * tc["warmup_ratio"]), total)
    scaler = torch.amp.GradScaler("cuda", enabled=(dev == "cuda"))
    weight = None
    if tc.get("class_weighting", "balanced") == "balanced":
        n = np.bincount(ytr, minlength=2).astype(float)
        weight = torch.tensor(len(ytr) / (2.0 * np.clip(n, 1, None)), dtype=torch.float32, device=dev)

    hist, best, best_state, stale = [], -1.0, None, 0
    for epoch in range(1, tc["epochs"] + 1):
        t0 = time.time()
        model.train()
        order = rng.permutation(len(ttr))
        losses = []
        for i in range(0, len(order), bs):
            idx = order[i:i + bs]
            b = tok([ttr[j] for j in idx], padding=True, truncation=True, max_length=ml, return_tensors="pt").to(dev)
            y = torch.tensor(ytr[idx], device=dev)
            with torch.autocast(device_type=dev, dtype=torch.float16, enabled=(dev == "cuda")):
                logits = model(**b).logits.float()
            loss = torch.nn.functional.cross_entropy(logits, y, weight=weight)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            losses.append(loss.item())
        p = _scores(model, tok, tes, ml, bs * 2, dev)
        auc = float(roc_auc_score(yes, p))
        h = {"epoch": epoch, "train_loss": float(np.mean(losses)),
             "val_loss": float(log_loss(yes, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1])), "val_auc": auc,
             "val_ap": float(average_precision_score(yes, p)), "val_score_std": float(p.std()),
             "seconds": round(time.time() - t0, 1)}
        hist.append(h)
        warn = "   <-- score spread ~0: collapsing" if p.std() < 0.02 else ""
        log(f"      epoch {epoch}: train_loss {h['train_loss']:.3f} stop-set AUC {auc:.3f} std {p.std():.3f} ({h['seconds']}s){warn}")
        if auc > best:
            best, stale = auc, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
            if stale >= tc["patience"]:
                log(f"      early stop: no stop-set AUC gain for {tc['patience']} epochs")
                break
    model.load_state_dict(best_state)
    return model, hist


def _save_model(model, tok, d: Path, fp16: bool):
    d.mkdir(parents=True, exist_ok=True)
    m = model.half() if fp16 else model
    m.save_pretrained(d)
    tok.save_pretrained(d)


def _load_model(d: Path, dev: str):
    from transformers import AutoModelForSequenceClassification
    return AutoModelForSequenceClassification.from_pretrained(d).float().to(dev).eval()


def train_signal(cfg: dict, run_dir: Path, tr: pd.DataFrame, va: pd.DataFrame, ytr: np.ndarray, gtr: np.ndarray,
                 yva: np.ndarray, log=print, fp: str = "") -> dict:
    """Run (or resume) the 5-fold fine-tune. Returns {'oof': train-length array, 'val': validation array, 'history': ...}."""
    tc = cfg["signals"]["textual"]
    dev = _device()
    log(f"  T: XLM-R {'(TINY test model) ' if tc.get('tiny') else ''}on {dev}; "
        f"{cfg['cv']['folds']} folds, up to {tc['epochs']} epochs each, class weighting={tc.get('class_weighting')}")
    if dev == "cpu" and not tc.get("tiny"):
        log("  WARNING: no GPU found. XLM-R fine-tuning on CPU will take many hours. Use Colab (T4).")
    tok = _tokenizer(tc)
    ttr, tva = _texts(tr), _texts(va)
    folds = fold_indices(ytr, gtr, cfg["cv"]["folds"], cfg["seed"])
    out_dir = run_dir / "xlmr"
    out_dir.mkdir(parents=True, exist_ok=True)
    oof = np.full(len(ytr), np.nan)
    val_parts, history = [], {}
    for k, (tri, vai) in enumerate(folds):
        fd = out_dir / f"fold{k}"
        done = fd / "done.npz"
        if done.exists():
            z = np.load(done)
            if "fp" in z.files and fp and str(z["fp"]) != fp:
                raise SystemExit(f"XLM-R fold {k + 1} was trained with a different config/code/split "
                                 f"(fingerprint {str(z['fp'])} vs {fp}). Start a new run or delete runs/<id>/xlmr.")
            oof[vai] = z["oof"]
            val_parts.append(z["val"])
            history[str(k)] = json.loads((fd / "history.json").read_text())
            log(f"  fold {k + 1}/{len(folds)}: already done, resuming (held-out AUC {roc_auc_score(ytr[vai], z['oof']):.3f})")
            continue
        log(f"  fold {k + 1}/{len(folds)}: train {len(tri)} / held-out {len(vai)}")
        inner_k = max(int(round(1 / tc["inner_val_fraction"])), 2)
        itr, ies = next(StratifiedGroupKFold(n_splits=inner_k, shuffle=True, random_state=cfg["seed"] + k)
                        .split(np.zeros(len(tri)), ytr[tri], gtr[tri]))
        a, b = tri[itr], tri[ies]
        model, hist = _fit_one(tc, tok, [ttr[i] for i in a], ytr[a], [ttr[i] for i in b], ytr[b], cfg["seed"] + k, dev, log)
        p_oof = _scores(model, tok, [ttr[i] for i in vai], tc["max_length"], tc["batch_size"] * 2, dev)
        p_val = _scores(model, tok, tva, tc["max_length"], tc["batch_size"] * 2, dev)
        _save_model(model, tok, fd / "model", tc.get("save_fp16", True))
        (fd / "history.json").write_text(json.dumps(hist, indent=2), encoding="utf-8")
        np.savez(done, oof=p_oof, val=p_val, fp=fp, vai=vai)
        oof[vai] = p_oof
        val_parts.append(p_val)
        history[str(k)] = hist
        log(f"  fold {k + 1}: held-out AUC {roc_auc_score(ytr[vai], p_oof):.3f}  validation AUC {roc_auc_score(yva, p_val):.3f}")
        del model
        if dev == "cuda":
            import torch
            torch.cuda.empty_cache()
    val = np.mean(val_parts, axis=0)
    (run_dir / "xlmr_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    return {"oof": oof, "val": val, "history": history}


def score_new(cfg: dict, run_dir: Path, df: pd.DataFrame) -> np.ndarray:
    """Mean probability of the saved fold models (used for the sealed test split and new listings)."""
    tc = cfg["signals"]["textual"]
    dev = _device()
    texts = _texts(df)
    parts = []
    for fd in sorted((run_dir / "xlmr").glob("fold*")):
        tok = _tokenizer(tc, str(fd / "model"))
        model = _load_model(fd / "model", dev)
        parts.append(_scores(model, tok, texts, tc["max_length"], tc["batch_size"] * 2, dev))
        del model
    if not parts:
        raise SystemExit(f"No XLM-R fold models in {run_dir / 'xlmr'}; run the T signal first.")
    p = np.mean(parts, axis=0)
    p[np.array([not t.strip() for t in texts])] = np.nan
    return p
