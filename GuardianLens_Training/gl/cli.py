"""Command line: python -m gl <command>"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from . import data as D
from .config import load_config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gl", description="GuardianLens training workspace (V + T + B -> fusion -> calibration -> bands)")
    ap.add_argument("--config", help="path to config.yaml (default: workspace config.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="verify frozen splits (hashes, group leakage, class counts, images)")
    c.add_argument("--freeze", action="store_true", help="(re)write split_manifest.json from the current CSVs")

    a_ = sub.add_parser("all", help="new run (or --run to resume) -> signals B, V, references [, T] -> fusion -> validation report. Never touches test")
    a_.add_argument("--tag", default="run")
    a_.add_argument("--run", help="resume an existing run id instead of creating one")
    a_.add_argument("--xlmr", action="store_true", help="include signal T as an XLM-R fine-tune (5 folds, GPU)")
    a_.add_argument("--text-cues", action="store_true",
                    help="include signal T as TF-IDF + text-cue logistic regression (methodology v2, CPU only)")
    a_.add_argument("--no-visual", action="store_true", help="skip signal V")
    a_.add_argument("--visual-metadata", action="store_true",
                    help="add image count/resolution/size to V (strong in exploration, NOT in the methodology; report as an extension)")
    a_.add_argument("--force", action="store_true", help="retrain signals already present in the run")

    n = sub.add_parser("new", help="create an empty run folder and print its id")
    n.add_argument("--tag", default="run")

    s = sub.add_parser("signal", help="train ONE signal into a run: B, V, T, text_baseline or tabular_ext")
    s.add_argument("key", choices=["B", "V", "T", "text_baseline", "tabular_ext"])
    s.add_argument("--run", default="latest")
    s.add_argument("--force", action="store_true")

    f = sub.add_parser("fuse", help="out-of-fold fusion of the trained signals + calibration + bands + validation report")
    f.add_argument("--run", default="latest")

    e = sub.add_parser("evaluate", help="rebuild validation metrics, charts and report for a run")
    e.add_argument("--run", default="latest")

    t = sub.add_parser("final", help="score the sealed TEST set ONCE with a finished run")
    t.add_argument("--run", default="latest")
    t.add_argument("--force", action="store_true")

    p = sub.add_parser("predict", help="score new listings with a trained run")
    p.add_argument("--run", default="latest")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)

    a = ap.parse_args(argv)
    cfg = load_config(a.config)

    if a.cmd == "check":
        if a.freeze:
            D.write_manifest(cfg)
        rep = D.verify(cfg)
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1

    from . import pipeline as P

    if a.cmd == "new":
        print(P.new_run(cfg, a.tag).name)
        return 0
    if a.cmd == "all":
        cfg = copy.deepcopy(cfg)
        if a.no_visual:
            cfg["signals"]["visual"]["enabled"] = False
        if a.visual_metadata:
            cfg["signals"]["visual"]["include_image_metadata"] = True
        if a.xlmr and a.text_cues:
            raise SystemExit("choose one: --xlmr or --text-cues")
        if a.text_cues:
            cfg["signals"]["textual"]["impl"] = "cues"
        elif a.xlmr:
            cfg["signals"]["textual"]["impl"] = "xlmr"
        run = P.run_all(cfg, a.tag, a.run, a.xlmr or a.text_cues, a.force)
        print(f"\nOpen the report:  {run / 'report.html'}")
        return 0
    if a.cmd == "signal":
        P.train_signal(cfg, P.resolve_run(cfg, a.run), a.key, a.force)
        return 0
    if a.cmd == "fuse":
        run = P.resolve_run(cfg, a.run)
        P.fuse(cfg, run)
        print(f"\nOpen the report:  {run / 'report.html'}")
        return 0
    if a.cmd == "evaluate":
        from .report import evaluate_validation
        evaluate_validation(cfg, P.resolve_run(cfg, a.run))
        return 0
    if a.cmd == "final":
        run = P.resolve_run(cfg, a.run)
        res = P.final_test(cfg, run, a.force)
        m = res["models"]["fusion"]
        print(f"test fusion ROC AUC {m['roc_auc']['point']:.3f}  PR AUC {m['pr_auc']['point']:.3f}\nOpen the report: {run / 'report.html'}")
        return 0
    if a.cmd == "predict":
        out = P.predict_file(cfg, P.resolve_run(cfg, a.run), Path(a.input), Path(a.output))
        print(f"scored {len(out)} listings -> {a.output}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
