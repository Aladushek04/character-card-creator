# Character Card Generator

Generates Character Card V3 cards for **character-tavern.com** from a short brief, using the
local OpenAI-compatible inference endpoint at `http://127.0.0.1:8765`. Optionally takes a
photo, uses it as the visual reference for the definition **and** as the card portrait.

No site automation: the tool writes `card.json` + `card.png` for manual import in the CT Studio.

## Verified environment

- Server: `http://127.0.0.1:8765`, OpenAI-compatible (`/health`, `/v1/models`,
  `/v1/chat/completions`, `/tokenize`), `response_format: json_schema` supported.
- Loaded model: `Huihui-Qwen3.6-35B-A3B-abliterated-ggml-model-Q4_K.gguf`, modalities
  `["text","image"]` (vision requires the `mmproj` projector, already loaded on the server).
- Measured locally on 800×1200 photos: ~977 prompt tokens per image, ~8 tok/s generation.
- Python 3.11+ and Pillow. No other third-party packages (stdlib `urllib`, `tomllib`).

## Card format (derived from the 39 CT exports in this project root)

Every card is `chara_card_v3` / `3.0`. The `chara` and `ccv3` PNG chunks contain the **same**
V3 object; newer exports also carry compressed `zTXt` copies. Field usage:

| CT Studio field | Card field |
|---|---|
| Definition | `data.description` |
| Greeting | `data.first_mes` |
| Public description / catalog blurb | `data.creator_notes` |
| Tags | `data.tags` |
| Display name | `data.name` |
| In-chat name | `data.nickname` |

`tagline`, content warnings, Original-content flag and visibility are **not stored in the
card file** — CT leaves them empty on import and they must be set in the Studio. The model
still writes a suggested tagline, printed after generation.

Generated portraits are cropped to 2:3 (default 800×1200, CT accepts up to 20 MB).

## Writing Tips.md compliance

The rules in `Writing Tips.md` are enforced in the prompt, the JSON schema, and a validator
that retries generation on failure:

- **Definition:** natural language only, no W++/bracket/pseudo-code templates; `{{char}}` and
  `{{user}}` macros instead of fixed names; behaviour described rather than listed as
  adjectives; explicit age 21+; 3500–6000 characters (minimum 200, anti-spam floor 1200).
- **Legacy fields:** `personality`, `scenario`, `mes_example`, `post_history_instructions`
  are always empty — the tips warn they waste token budget and degrade modern models.
- **Greeting:** 800–3200 characters, addresses `{{user}}` by macro, Markdown allowed, one
  `https://files.catbox.moe/...` image is the only permitted link.
- **Field limits:** name 3–80, tagline 10–150, public description ≥10, 1–100 tags, in-chat
  name ≤50.
- **Prohibited content:** hard gates for underage presentation (including "high school" and
  other underage coding, no stated age, and minor user personas), real identifiable people,
  non-catbox URLs, impersonation, and placeholder/spam text.
- **Language:** card text in English, roleplay chat (and the first message) in Russian by
  default. Adjust `card.narrative_language` / `card.definition_language` if needed.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Configure

Edit `config.toml`:

- `server.base_url` / `server.model` — startup defaults only; the web UI can change both at
  runtime. `server.allow_remote` is `false` (loopback endpoints only for now).
- `generation.max_tokens` — output length; 2600 fits a full definition.
- `generation.min_definition_chars` / `max_definition_chars` — CT's 3500–6000 character target.
- `generation.max_description_tokens` — secondary token ceiling measured with `/tokenize` (1600).
- `card.narrative_language` / `card.definition_language` — card text in English, roleplay
  chat and first message in Russian by default.
- `card.content_rating` — `spicy`, `mature` or `explicit`.

## Use

```powershell
# text only
python run.py --concept "A retired detective who reads memories from objects" --name "Vera"

# photo is both the visual reference and the portrait
python run.py -i
python run.py --concept "..." --photo .\ref.jpg --rating mature

# photo as portrait only (the model never sees it)
python run.py --concept "..." --photo .\ref.jpg --no-photo-in-prompt

# print the assembled prompts without calling the server
python run.py --concept "..." --dry-run
```

Output goes to `generated/<name>.json` and `generated/<name>.png`. Add `--bio path\to\bio.md`
to feed a biography into the definition.

## Web service (NiceGUI)

Chosen over Reflex, Streamlit, Shiny and Anvil: it is local-first and pure Python on FastAPI,
handles uploads and stateful per-client UI directly, needs no cloud account, and does not fight
a chat interface with Streamlit's rerun model.

```powershell
python -m pip install -r requirements.txt
python run_service.py          # http://127.0.0.1:8080
```

The UI has four tabs:

- **Connection** — enter any loopback base URL (default `http://127.0.0.1:8765`) and connect.
  The service probes `/health`, `/v1/models`, `/props` and `/slots`, then shows: online/ready
  state, supported models with their modalities, the currently loaded model and its path,
  context size (65,536 here), VLM module status, build info, slots, and sleep state. Pick the
  model from the discovered list; creation, photo analysis and chat all use the selected model.
  Generation and chat are blocked until the endpoint is ready. Generic OpenAI-compatible
  servers without `/props` still work — context/VLM fall back to `/slots` and `/v1/models`.
- **Create** — brief form, biography upload, photo upload, adult-subject confirmation,
  "Analyze photo", then "Generate character". Photo analysis is a structured vision pass that
  extracts hair, eyes, face, body build, distinctive marks, attire and adult feature/zone notes
  (`service/photo.py`); it is injected into the definition. Underage-coded photos are rejected.
- **Chat** — one character per chat. Every character owns `characters/<slug>/chat.json`; the
  system prompt is rebuilt from that character's card on every turn, and history is trimmed to
  `service.chat_context_budget` tokens. Switching characters never mixes context. Optional image
  attachment per message.
- **Card** — definition/greeting preview, portrait, and direct download links for the V3
  `card.json` and `card.png`.

The sidebar can also import an existing CT PNG/JSON card into the library. Runtime data
(`characters/`, `uploads/`, `generated/`) is gitignored.

Repository: https://github.com/Aladushek04/character-card-creator

## Import into Character Tavern

1. Studio → **Import a card** → the generated PNG. Leave "Import legacy advanced definitions"
   unchecked.
2. Fill the required **Tagline** (suggestion is printed by the CLI).
3. Tick the correct content warnings: **Spicy** or **Mature** for adult cards.
4. Check tags, remove meaningless ones, set visibility and Original content.
5. Publish. The portrait is already 2:3 from the PNG import.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Content rules enforced in the prompt

Original fictional characters only, all characters 21+, no real identifiable people, no
underage characters or underage coding, no writing for `{{user}}`, no links outside the
permitted catbox image syntax, no spam placeholders. Validation is deterministic and retries
with the exact errors; `normalize_macros()` also rewrites a fixed character name into
`{{char}}` as a backstop. This is one deterministic local tool, not a CT client.

## Status

Built and unit-tested locally (21 tests). `json_schema` output, vision input, `/tokenize` and
the live chat path were exercised against the running endpoint during development. The web UI
was loaded in a real browser; the Connection tab reported ONLINE · READY with the real loaded
model, 65,536-token context, VLM enabled and one slot. A full card
generation is only run when you invoke `run.py` or press "Generate character"; generation length
and wording depend on the model and the configured sampling. Card import into CT is a manual
step and was not performed here.
