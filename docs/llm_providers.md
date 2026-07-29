# Cloud LLM providers & zero-cost showcase plan

Decision record, researched 2026-07-29. Free tiers are volatile — numbers
below were verified against official docs where possible; re-check before
relying on a specific quota.

## How the studio talks to a cloud API

`ChatSession` (`ui/chat.py`) selects its transport at construction:

1. an injected `runner` (tests, future transports),
2. `ApiRunner` — any **OpenAI-compatible** `/chat/completions` endpoint,
   selected when the environment is configured:

   ```sh
   export DRAFTSMITH_API_BASE="https://generativelanguage.googleapis.com/v1beta/openai"
   export DRAFTSMITH_API_MODEL="gemini-2.5-flash"
   export DRAFTSMITH_API_KEY="..."
   draftsmith ui
   ```

3. fallback: the local `claude` CLI in print mode (the original M2 setup).

The runner is stdlib-only (urllib), sends the M2 system prompt
(`agent_prompt.md`) as the `system` message, and raises `ToolError` on
HTTP errors / bad response shapes so the chat loop surfaces them.

## Free-tier provider picks (July 2026)

| Provider | Endpoint base | Free limits (approx) | Notes |
|---|---|---|---|
| **Google Gemini** (primary) | `https://generativelanguage.googleapis.com/v1beta/openai` | Flash ~10 RPM / 250 RPD; Flash-Lite ~15 RPM / 1,000 RPD; Pro ~5 RPM / 100 RPD (per-account, check AI Studio) | No card. Strongest free models (Gemini 3.x/2.5 Flash class). Trains on free-tier data; quotas have shrunk without notice before. |
| **Mistral** (volume) | `https://api.mistral.ai/v1` | ~1 req/s, ~1B tokens/month (Experiment tier) | No card, phone verification, data-training opt-in. Biggest card-free volume anywhere. |
| **NVIDIA NIM** (fallback) | `https://integrate.api.nvidia.com/v1` | ~40 RPM, no daily cap | No card. Huge open-model catalog (Llama, DeepSeek, Qwen, Nemotron). Forum-sourced limits, not an SLA. |
| **OpenRouter** (experiments) | `https://openrouter.ai/api/v1` | `:free` models: 20 RPM, 50 RPD (1,000 RPD after one-time $10 credit) | Free catalog rotates weekly. The $10 doubles as paid fallback to every model on the market. |

Not chosen: **Groq** (daily token caps ≈ only 20–45 draftsmith-sized
requests/day on 70B+ models, though best privacy posture — no training),
**Cerebras** (now requires a card; catalog shrinking), **SambaNova**
(20 req/day), **GitHub Models** (retired 2026-07-30), **HF Inference**
(~$0.10/month credits), **Cohere** (1,000 calls/month). **OpenAI /
Anthropic**: no free API tier (Anthropic: one-time ~$5 trial credit only).

## Zero-cost public showcase (GitHub-anchored)

GitHub Pages is static-only, and the 2026 free-hosting landscape is thin
(HF Spaces Gradio/Docker now paid; Fly/Railway effectively gone; Render
free spins down after 15 min idle; Cloud Run needs a card). The plan:

1. **Repo + README** — screenshots/GIF, sample renders, the FP1 story.
2. **Live demo on GitHub Pages via Pyodide** — the whole compute
   pipeline runs in-browser: `shapely` and `matplotlib` ship in the
   Pyodide distribution, and `ezdxf` publishes a pure-Python wheel that
   `micropip` installs from PyPI. The stdlib server layer disappears;
   its JSON routes become JS→Pyodide calls. No servers, no cold starts,
   no cost, never expires. (~15–40 MB first load — needs a loading
   screen.)
3. **LLM calls from the static demo** — two options:
   - *BYO-key panel* targeting OpenRouter (CORS-friendly, free models;
     key stays in the browser), with canned demo turns as the no-key
     fallback;
   - *own key kept secret*: a **Cloudflare Workers free-plan proxy**
     (100k req/day, secrets, rate-limitable) in front of Gemini/Mistral,
     called from the Pages frontend. Gemini's own browser-CORS behavior
     is inconsistent — don't call it directly from the browser.
4. **"Open in Codespaces" badge** — visitors run the real Python studio
   on their own free 120 core-hours/month; costs the repo owner nothing.
5. Fallback if the Pyodide port is rejected: Render free web service
   (15-min spin-down, ~1-min cold start — note it in the README).

## Longer term: bigger models, fine-tuning, experiments

- **Frontier-class open-model experiments, $0**: stack Gemini free tier +
  NVIDIA NIM + OpenRouter `:free` (+ Groq/Cerebras for speed bursts).
- **Fine-tuning (M3/M5 synthetic-dataset work)**: Gemini fine-tuning was
  discontinued for individuals — the zero-cost path is **QLoRA via
  Unsloth on Kaggle** (30 guaranteed GPU-h/week on 2×T4; tunes
  Qwen3 ≤14B / Gemma 3 class, exactly right for FP1 text SFT), Colab as
  overflow. Serve tunes locally via **Ollama** (GGUF export), adapters
  on HF Hub. **Modal's recurring $30/month free credits** cover
  A100-class bursts (~12 h/mo) when 16 GB T4s cap out.
- **Managed tuning when it matters**: Together/Fireworks LoRA at
  ~$0.50/M training tokens, $4/job minimum — tens of dollars for a
  serious synthetic-dataset run.
