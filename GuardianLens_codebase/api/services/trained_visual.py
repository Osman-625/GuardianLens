"""Local CLIP/SSCD inference with the selected run's approved reference corpus."""

from __future__ import annotations

import importlib
import io
from pathlib import Path
from typing import Any

from api.models.domain import AssessmentRecord
from api.services.trained_models import verify_train_split


def load_reference_cache(path: Path) -> dict[str, dict[str, Any]]:
    """Reads the visual reference cache saved by the training workspace.

    The file is a compressed .npz holding, for every approved training listing, its CLIP and SSCD
    image embeddings and its CLIP title embedding. The result is the same mapping the training
    workspace's own loader returns (listing id to {"clip", "sscd", "title"} float32 arrays), but
    each array is read ONCE. A compressed npz decompresses a whole array every time a key is read,
    and the training loader reads three of them per listing inside its loop, which takes minutes
    for about two thousand listings; reading each array once takes a fraction of a second.

    @returns An empty mapping when the file does not exist.
    """
    import numpy as np

    if not path.exists():
        return {}
    with np.load(path, allow_pickle=False) as raw:
        ids = raw["ids"].tolist()
        counts = raw["n"].astype(int).tolist()
        clip = raw["clip"].astype(np.float32)
        sscd = raw["sscd"].astype(np.float32)
        title = raw["title"].astype(np.float32)
    store: dict[str, dict[str, Any]] = {}
    offset = 0
    for index, listing_id in enumerate(ids):
        count = counts[index]
        # Copies, so a listing's arrays do not keep the whole reference matrix alive.
        store[listing_id] = {
            "clip": clip[offset : offset + count].copy(),
            "sscd": sscd[offset : offset + count].copy(),
            "title": title[index].copy(),
        }
        offset += count
    return store


class TrainedVisual:
    """The visual feature extractor: CLIP and SSCD models plus the approved reference corpus.

    It turns a listing's photos and title into the feature table the saved visual classifier
    expects, comparing the photos with the approved training reference images only.
    """

    def __init__(self, workspace: Path, cfg: dict[str, Any], meta: dict[str, Any]) -> None:
        """Loads the reference embeddings, the CLIP model, and the SSCD model from local files.

        Raises FileNotFoundError when an asset is missing (the caller then reports the visual
        signal as unavailable) and RuntimeError for a run that used image metadata. Nothing is
        downloaded: serving uses the local copies only.
        """
        from urllib.parse import urlparse

        visual = importlib.import_module("gl.visual")

        train_path = verify_train_split(workspace, meta)
        cache_dir = workspace / cfg["paths"]["cache_dir"]
        cache = cache_dir / f"visual__{visual._slug(cfg['signals']['visual']['clip_model'])}.npz"
        sscd_path = (
            cache_dir / "sscd" / Path(urlparse(cfg["signals"]["visual"]["sscd_url"]).path).name
        )
        if not cache.is_file() or not sscd_path.is_file():
            raise FileNotFoundError("CLIP/SSCD reference cache or SSCD checkpoint is missing.")
        if cfg["signals"]["visual"].get("include_image_metadata"):
            raise RuntimeError(
                "Select the latest noMeta run; this visual adapter excludes image metadata."
            )
        pd = importlib.import_module("pandas")
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")

        self.cfg = cfg
        self.ref = pd.read_csv(train_path, usecols=["listing_id", "group_id"])
        # Not visual._load_cache: that loader is quadratic on a compressed file (see
        # load_reference_cache), which would make every API start-up take several minutes.
        cached = load_reference_cache(cache)
        if not set(self.ref["listing_id"]).issubset(cached):
            raise FileNotFoundError("Some approved training reference embeddings are missing.")
        self.store = {lid: cached[lid] for lid in self.ref["listing_id"]}
        if not any(len(row["sscd"]) for row in self.store.values()):
            raise FileNotFoundError("The approved reference corpus has no image embeddings.")
        self.device = visual._device()
        model_name = cfg["signals"]["visual"]["clip_model"]
        try:
            # Serving uses downloaded assets only; model downloads belong to setup.
            self.clip = (
                transformers.CLIPModel.from_pretrained(model_name, local_files_only=True)
                .to(self.device)
                .eval()
            )
            self.processor = transformers.CLIPProcessor.from_pretrained(
                model_name, local_files_only=True
            )
        except OSError as exc:
            raise FileNotFoundError("The local CLIP checkpoint is missing.") from exc
        self.sscd = torch.jit.load(str(sscd_path), map_location=self.device).eval()
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)

    def features(self, assessment: AssessmentRecord) -> Any:
        """Builds the visual feature table for one assessment.

        Embeds the photos (CLIP and SSCD), the title, and the category, adds them to a copy of the
        reference store, and lets the training workspace compute the same features it trained on.
        The new embeddings stay in memory; the reference corpus itself is never changed.
        """
        import numpy as np

        pd = importlib.import_module("pandas")
        torch = importlib.import_module("torch")
        visual = importlib.import_module("gl.visual")
        from PIL import Image

        images = [
            Image.open(io.BytesIO(item.content)).convert("RGB")
            for item in assessment.images[: self.cfg["signals"]["visual"]["images_per_listing"]]
        ]
        if not images:
            raise ValueError("Visual inference requires at least one image.")
        lid = str(assessment.id)
        model_name = self.cfg["signals"]["visual"]["clip_model"]
        try:
            with torch.no_grad():
                inputs = self.processor(images=images, return_tensors="pt").to(self.device)
                clip = self.clip.get_image_features(**inputs)
                if not torch.is_tensor(clip):
                    clip = clip.pooler_output
                clip = torch.nn.functional.normalize(clip, dim=-1).cpu().numpy()
                pixels = torch.stack(
                    [
                        torch.from_numpy(
                            np.asarray(
                                im.resize((visual.SSCD_SIZE, visual.SSCD_SIZE)), dtype=np.float32
                            )
                            / 255.0
                        ).permute(2, 0, 1)
                        for im in images
                    ]
                ).to(self.device)
                sscd = (
                    torch.nn.functional.normalize(
                        self.sscd((pixels - self.mean) / self.std), dim=-1
                    )
                    .cpu()
                    .numpy()
                )
                title = visual._clip_text(
                    self.clip, self.processor, [assessment.title_for_inference], self.device
                )[0]
                category = visual._clip_text(
                    self.clip,
                    self.processor,
                    [f"a photo of {assessment.category.lower()}"],
                    self.device,
                )[0]
            # Seed the training helper's category cache so it never loads another encoder.
            visual._CAT_CACHE[(model_name, assessment.category)] = category
            store = dict(self.store)
            store[lid] = {"clip": clip, "sscd": sscd, "title": title}
            frame = pd.DataFrame(
                [{"listing_id": lid, "group_id": lid, "category": assessment.category}]
            )
            return visual.build_features(self.cfg, store, self.ref, frame)
        finally:
            for im in images:
                im.close()
            # The category is free text, so keeping its entry would grow the cache without bound.
            visual._CAT_CACHE.pop((model_name, assessment.category), None)
