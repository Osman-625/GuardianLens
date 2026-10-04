# GuardianLens

Multilingual (EN/BM/ZH) marketplace-listing fraud detection, built for an INTI International University final year project. This monorepo holds the five system workspaces. Datasets, images, run outputs, databases and secrets are git-ignored and stay local.

| Workspace | Purpose |
|---|---|
| `URL_Crawler/` | Collects Carousell and Mudah listing URLs across 12 categories |
| `GuardianLens_Data_Collector_v_1.0.0/` | FastAPI collector plus Chrome extension that captures listings, screenshots and seller signals |
| `GuardianLens_Annotation/` | Rule-based weak labelling, annotation guidelines, 3-pass AI + human annotation pipeline |
| `GuardianLens_Training/` | Text, visual and metadata fusion model training (Colab-ready package, notebooks, evaluation) |
| `GuardianLens_codebase/` | Application: FastAPI API, Next.js frontend, ML inference package, DB schema |

Each workspace has its own README or `docs/` folder with setup and verification steps. Copy `.env.example` to `.env` in the workspaces that have one and fill in your own keys.

`GuardianLens_Approved_Dataset/` (approved listings and images) is intentionally not tracked.
