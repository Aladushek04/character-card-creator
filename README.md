# Character Card Generator

Generates Character Card V3 cards for **character-tavern.com** from a short brief, using the
local OpenAI-compatible inference endpoint at `http://127.0.0.1:8765`. Optionally takes a
one to five reference photos, used as visual references for the definition; one of them is
also the card portrait. The service does generation only — there is no chat.

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
- `generation.max_tokens` — output cap (2200). At the measured ~8 tok/s one card takes 4–6 min;
  `retries = 1` allows at most two passes. CT's 3500–6000 char definition target is reported as
  a note, not a hard failure, so a slightly shorter card does not trigger a full regeneration.
- `generation.min_definition_chars` / `max_definition_chars` — CT's 3500–6000 character target.
- `generation.max_description_tokens` — secondary token ceiling measured with `/tokenize` (1600).
- `card.narrative_language` / `card.definition_language` — card text in English, roleplay
  chat and first message in Russian by default.
- `card.content_rating` — `spicy`, `mature` or `explicit`.

## Use

```powershell
# text only
python run.py --concept "A retired detective who reads memories from objects" --name "Vera"

# one to five reference photos; the first is the portrait
python run.py -i
python run.py --concept "..." --photo .\ref1.jpg .\ref2.jpg .\ref3.jpg --rating mature

# photos as portrait only (the model never sees them)
python run.py --concept "..." --photo .\ref1.jpg --no-photo-in-prompt

# print the assembled prompts without calling the server
python run.py --concept "..." --dry-run
```

Output goes to `generated/<name>.json` and `generated/<name>.png`. Add `--bio path\to\bio.md`
to feed a biography into the definition.

## Web service (NiceGUI)

Chosen over Reflex, Streamlit, Shiny and Anvil: local-first, pure Python on FastAPI, native
multi-file uploads and a configurable image gallery, no cloud account.

```powershell
python -m pip install -r requirements.txt
python run_service.py          # http://127.0.0.1:8080
```

The UI has three tabs:

- **Connection** — enter any loopback base URL and connect. The service detects the flavour:
  llama.cpp/bmoe (`/health`, `/props`, `/slots`, `/tokenize`), **LM Studio** (`/v1/models`,
  `/api/v1/models`) or generic OpenAI-compatible (`/v1/models` only). It shows online/ready
  state, model list with modalities, loaded model and path, context, max context, VLM module,
  quantization, reasoning support, build info and slots. Pick the model from the list; creation,
  photo analysis and generation all use it. Generation is blocked until ready.
  - LM Studio does not expose `/health`, `/props` or `/tokenize`: reachability comes from
    `/v1/models`, loaded instances/context/capabilities from `/api/v1/models`, and token counts
    are estimated. A **Load model** button calls `/api/v1/models/load` with the chosen context
    when the model is unloaded. Reasoning is disabled in requests (`"reasoning": false`) so it
    cannot consume the whole token budget with an empty `content`.
  - Verified LM Studio endpoint: `http://127.0.0.1:1234`,
    `qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp@iq3_m` (IQ3_M, 27B, vision-capable,
    max context 262,144). `json_schema` output and image input both work there.
- **Create** — brief form, biography upload, **up to five photos**, adult-subject confirmation,
  "Analyze photos", then "Generate character". Uploaded photos are shown in a gallery at full
  aspect (`object-fit: contain`, no cropping) with individual Remove buttons and a dropdown to
  choose which one becomes the portrait. Photo analysis is a structured vision pass per photo
  that extracts hair, eyes, face, body build, distinctive marks, attire and adult feature/zone
  notes (`service/photo.py`); all analyses are injected into the definition. Any underage-coded
  photo blocks the whole batch.
- **Card** — definition/greeting preview, portrait, and direct download links for the V3
  `card.json` and `card.png`.

The sidebar lists generated characters. Runtime data (`characters/`, `uploads/`, `generated/`)
is gitignored. There is no chat UI and no chat storage.

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

Built and unit-tested locally (27 tests). `json_schema` output and vision input were exercised
against both the llama.cpp and LM Studio endpoints. The web UI was loaded in a real browser:
three tabs only (no chat), a three-photo batch produced three full-aspect previews with
`object-fit: contain`, and the Connection tab reported ONLINE · READY with the loaded model,
context and VLM state. A full card generation is only run when you invoke `run.py` or press
"Generate character"; generation length and wording depend on the model and sampling. Card
import into CT is a manual step and was not performed here.
