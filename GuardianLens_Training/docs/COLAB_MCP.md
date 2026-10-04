# Driving Colab training from Claude Code (colab-mcp)

## What is configured

`C:\Users\cusma\OneDrive\Desktop\FYP Project\.mcp.json`:

```json
{ "mcpServers": { "colab-mcp": { "command": "uvx", "args": ["git+https://github.com/googlecolab/colab-mcp"], "timeout": 30000 } } }
```

`.claude/settings.local.json` already lists `colab-mcp` under `enabledMcpjsonServers`.

Verified on this machine: `uvx` is installed and the server starts (`colab-mcp --help` works). Its first launch needs about
80 s to fetch and build, which is longer than the 30 s `timeout`, so it was **pre-warmed**; a warm start takes about 6 s.
If you ever clear the uv cache, run `uvx git+https://github.com/googlecolab/colab-mcp --help` once before starting Claude Code.

## What colab-mcp is (from its README)

An MCP server that "bridges your local agent to a Colab session in the browser". It runs locally, needs a client that supports
`notifications/tools/list_changed` (Claude Code does), and its tools appear after you connect a Colab session. The README does not
document the tool list, GPU handling or file transfer, so the steps below use only plain "run this code in the Colab session".

## Connect it (one time per Claude Code session)

1. **Restart Claude Code in `C:\Users\cusma\OneDrive\Desktop\FYP Project`.** MCP servers are loaded only at startup; a server added
   mid-session is not available. Approve `colab-mcp` if prompted, then check `/mcp` shows it as connected.
2. In Chrome, open Colab, open `GuardianLens_Colab.ipynb` (upload it from the package or Drive), set **Runtime -> T4 GPU**.
3. Upload `dist/GuardianLens_Colab_Package.zip` to the top of Google Drive.
4. Tell Claude: *"Connect to my Colab session and run the training."* Follow any connect prompt the server shows in the browser.
5. When the notebook asks to **mount Google Drive**, click Allow in the browser yourself (Google requires a human click).

## What Claude should run through it (same as the notebook cells)

```text
cell 1  GPU check + Drive mount                      (you click "Allow")
cell 2  unzip package, link runs/ and data/cache to Drive, pip install -r requirements.txt
cell 3  python -m gl check                           -> must print "ok": true
cell 4  python -m gl all --xlmr --tag colab          (25-45 min on a T4; resumable)
cell 5  print the metrics tables, show every chart inline
```

Long jobs: run cell 4 as `nohup python -m gl all --xlmr --tag colab > train.log 2>&1 &` and poll `tail -n 30 train.log`, so a slow
MCP call or browser tab sleep cannot kill it. `runs/` lives on Drive and every signal and every XLM-R fold checkpoints, so after a
disconnect re-run cells 1-3 and `python -m gl all --run <run id> --xlmr`.

## Rules for the agent driving it

* Train only inside Colab. Do not train on the local machine.
* Do **not** run `python -m gl final` (the sealed test split) unless the user explicitly says so; it can only be run once per run.
* Report negative results as they are (a collapsed or chance-level signal is a finding, not something to hide).
* Do not change `data/splits` or `split_manifest.json`; `gl check` will fail if they are altered.

## If it does not connect

* `/mcp` does not list `colab-mcp`: restart Claude Code from the folder that contains `.mcp.json`.
* It times out on start: run the warm-up command above.
* No Colab tools appear: the browser session is not connected yet (step 2/4). Server logs are in
  `%TEMP%\colab-mcp-logs\`.
* Without MCP, the notebook alone does the whole job: open it in Colab and run the cells top to bottom.
