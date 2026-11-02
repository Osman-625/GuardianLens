# GuardianLens

**Explainable multimodal fraud-risk detection for Malaysian online marketplaces.**
Final Year Project, INTI International University (Faculty of Data Science and Information Technology), by Osman Abdurahman Maalim.

## What it is

Malaysian consumer-to-consumer marketplaces leave the buyer alone to judge a listing before paying. GuardianLens is a buyer-facing decision-support tool for **Mudah.my** and **Carousell Malaysia** product listings. It reads a listing's photos, text and seller details, combines three machine-learning signals into a calibrated **0 to 100 score** (100 is the lowest estimated risk) with a **Low / Moderate / High** risk band, and explains the result in plain language.

It never says "this is fraud" and never tells the buyer to buy or not to buy. It supports a decision; it does not make one.

## How it works

```
 photos ──► Visual signal (CLIP photo-title consistency, SSCD copy detection) ─┐
 text   ──► Textual signal (TF-IDF + scam-cue model)                           ├─► out-of-fold fusion ─► calibration ─► score 0-100 + band
 seller ──► Behavioural signal (XGBoost on price, category ratio, seller fields)┘                                        + SHAP-based explanation
```

Labels are *annotated risk* (suspicious + scam/fraud), not confirmed fraud.

## Repository layout

The project is a chain of five workspaces, from raw listings to a running app.

| Folder | Role |
|---|---|
| `URL_Crawler/` | Crawls candidate listing URLs from Carousell and Mudah across 12 categories |
| `GuardianLens_Data_Collector_v_1.0.0/` | Chrome extension plus local FastAPI app that captures listings, screenshots and seller signals, with AI-assisted extraction, privacy scrubbing, duplicate checks and human review |
| `GuardianLens_Annotation/` | Annotation rubric, rule engine for weak labels, three-pass AI + human annotation pipeline with a kappa gate |
| `GuardianLens_Training/` | The `gl` package: signals, fusion, calibration, seven-configuration ablation, SHAP, sealed test. Colab-ready |
| `GuardianLens_codebase/` | The application: Next.js frontend (7 screens), FastAPI `/api/v1`, SQLite storage, trained-model serving |

Each workspace has its own README or `docs/` folder with setup and verification steps. Copy `.env.example` to `.env` where one exists and add your own keys.

## Results (sealed test, 330 listings, scored once)

| Model | ROC AUC |
|---|---|
| Visual only | 0.573 |
| Textual only | 0.671 |
| Behavioural only | 0.729 |
| **Fusion (V + T + B)** | **0.799** (95% CI 0.749 to 0.849) |

Fusion beats the best single signal by +0.071 (95% CI +0.011 to +0.128). The share of listings that are risky rises from 6% in the Low band to 29% in Moderate and 64% in High.

## Honest limits

- Labels are annotated risk from an AI-assisted pipeline, not confirmed fraud.
- The textual signal is a TF-IDF + text-cue model. An XLM-RoBERTa fine-tune was attempted but collapsed, so it is not used in the final model.
- The visual signal is weak, and the test set is small, so confidence intervals are wide.
- The application in `GuardianLens_codebase/` still runs on **development stubs**, not the trained models. Stub scores must not be read as real results.

## Data

The dataset is **not** in this repository. It holds 2,209 approved listings (1,410 Carousell, 799 Mudah, 12 categories, about 11,000 photos), annotated as 1,625 legitimate, 379 suspicious, 193 scam/fraud and 12 insufficient evidence. Datasets, images, run outputs, databases and secrets are git-ignored and stay local.
