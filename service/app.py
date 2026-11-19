"""NiceGUI web interface: character generation from text and up to five photos.

No chat. The only job of this service is to produce Character Tavern V3 cards.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nicegui import app, run, ui

from cardgen.cli import load_config
from cardgen.generator import generate
from cardgen.schema import draft_warnings
from service.connection import ConnectionState
from service.photo import UnderageSubject, analyze_photos, format_analyses
from service.store import CharacterStore

ROOT = Path(__file__).resolve().parent.parent
MAX_PHOTOS = 5


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_ui(config: dict[str, Any]) -> None:
    store = CharacterStore(config["paths"].get("characters_dir", "characters"))
    server = config["server"]
    conn = ConnectionState(
        server["base_url"],
        server.get("model", ""),
        allow_remote=bool(server.get("allow_remote", False)),
        timeout_s=server["timeout_s"],
    )
    conn.probe()
    uploads = ROOT / config["paths"].get("uploads_dir", "uploads")
    uploads.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/files", str(ROOT))

    state: dict[str, Any] = {
        "slug": None,
        "bio": "",
        "photos": [],
        "portrait": None,
        "analyses": [],
    }

    with ui.header(elevated=True).classes("items-center"):
        ui.label("Character Card Studio").classes("text-h6")
        ui.label("generation from text + up to 5 photos").classes("ml-4 text-caption opacity-70")

    tabs = ui.tabs()
    with tabs:
        conn_tab = ui.tab("Connection")
        create_tab = ui.tab("Create")
        card_tab = ui.tab("Card")
    panels = ui.tab_panels(tabs, value=conn_tab)

    # ------------------------------------------------------------------ sidebar
    with ui.left_drawer().classes("w-72"):
        ui.label("Generated characters").classes("text-subtitle1")
        ui.label("Select one to inspect and download its card.").classes("text-caption opacity-70")
        char_list = ui.column().classes("w-full")

        def refresh_list() -> None:
            char_list.clear()
            with char_list:
                for item in store.list():
                    active = item["slug"] == state["slug"]
                    ui.button(
                        f"{item['name']} · {item['tagline'][:48]}",
                        on_click=lambda s=item["slug"]: select(s),
                    ).props("flat" if not active else "outline").classes("w-full text-left")

        def select(slug: str) -> None:
            state["slug"] = slug
            refresh_list()
            refresh_card()

    # --------------------------------------------------------------- connection
    with panels:
        with ui.tab_panel(conn_tab):
            ui.label("Connect to an inference endpoint").classes("text-subtitle1")
            ui.label(
                "Enter the base URL of a running OpenAI-compatible server. For now only "
                "loopback addresses (127.0.0.1 / localhost / ::1) are accepted."
            ).classes("text-caption opacity-70")
            url_in = ui.input("API base URL", value=conn.base_url).classes("w-full")
            with ui.row().classes("items-center gap-3"):
                conn_button = ui.button("Connect / refresh", icon="link")
                ctx_in = ui.number("Load context", value=32768, min=2048, max=262144)
                load_button = ui.button("Load model (LM Studio)", icon="download")
                status_label = ui.label("")
            model_select = ui.select(
                [], label="Model to use", with_input=True,
                on_change=lambda e: on_model(e.value),
            ).classes("w-full")
            conn_info = ui.column().classes("w-full")
            conn_error = ui.label("").classes("text-negative")
            updating_select = {"active": False}

            def render_conn() -> None:
                summary = conn.summary()
                status_label.set_text(
                    ("ONLINE" if summary["online"] else "OFFLINE")
                    + " · " + ("READY" if summary["ready"] else "NOT READY")
                ).classes("text-positive" if summary["ready"] else "text-negative")
                conn_error.set_text(summary["error"]).classes(
                    "text-caption opacity-70" if summary["online"] else "text-negative"
                )
                load_button.enable() if (
                    summary["api_flavor"] == "LM Studio" and not summary["loaded_instances"]
                ) else load_button.disable()
                ids = [m["id"] for m in summary["models"]]
                updating_select["active"] = True
                try:
                    model_select.set_options(ids)
                    model_select.value = summary["selected_model"]
                finally:
                    updating_select["active"] = False
                conn_info.clear()
                with conn_info:
                    ctx = summary["context"]
                    details = summary["model_details"].get(summary["selected_model"], {})
                    rows = [
                        ("Endpoint", summary["base_url"]),
                        ("API flavour", summary["api_flavor"]),
                        ("Server build", summary["build_info"] or "not reported"),
                        ("Loaded model", summary["loaded_model"] or "not loaded"),
                        ("Selected model", summary["selected_model"] or "none"),
                        ("Context", f"{ctx:,} tokens" if ctx else "unknown"),
                        ("Max context", f"{summary['max_context']:,} tokens" if summary["max_context"] else "unknown"),
                        ("VLM module", "enabled" if summary["vision"] else "not reported / disabled"),
                        ("Video / Audio", f"{summary['video']} / {summary['audio']}"),
                        ("Slots", ", ".join(
                            f"#{s['id']} ctx={s['n_ctx']} ({'busy' if s['processing'] else 'idle'})"
                            for s in summary["slots"]) or "not reported"),
                        ("Model path", summary["model_path"] or "not reported"),
                    ]
                    if details:
                        rows += [
                            ("Quantization", details.get("quant", "not reported")),
                            ("Parameters", details.get("params", "not reported")),
                            ("Reasoning support", str(details.get("reasoning", False))),
                        ]
                    lines = ["| Field | Value |", "|---|---|"] + [
                        f"| {k} | {str(v).replace('|', '/')} |" for k, v in rows
                    ]
                    ui.markdown("\n".join(lines))
                    if not summary["props_available"]:
                        ui.label(
                            "This server does not expose /props; context and VLM data come "
                            "from /v1/models and /slots where available."
                        ).classes("text-caption opacity-70")
                    if summary["api_flavor"] != "llama.cpp":
                        ui.label("Token counts are estimated (server has no /tokenize endpoint).") \
                            .classes("text-caption opacity-70")

            def on_model(value: str) -> None:
                if updating_select["active"]:
                    return
                conn.set_model(value)
                render_conn()

            async def do_connect() -> None:
                try:
                    await run.io_bound(conn.probe, url_in.value)
                except ValueError as exc:
                    ui.notify(str(exc), type="negative", timeout=8000)
                    return
                render_conn()
                ui.notify("Connected" if conn.ready else "Endpoint inspected — see status",
                          type="positive" if conn.ready else "warning")

            async def do_load() -> None:
                try:
                    await run.io_bound(conn.load_model, conn.selected_model, int(ctx_in.value or 32768))
                    render_conn()
                    ui.notify("Model loaded", type="positive")
                except Exception as exc:
                    ui.notify(str(exc), type="negative", timeout=8000)

            conn_button.on_click(do_connect)
            load_button.on_click(do_load)

            def require_ready() -> bool:
                if conn.ready:
                    return True
                ui.notify(
                    "Connect to a running endpoint and select a model on the Connection tab first",
                    type="warning", timeout=6000,
                )
                panels.value = conn_tab
                return False

            render_conn()

    # ------------------------------------------------------------------- create
        with ui.tab_panel(create_tab):
            ui.label("1 · Brief").classes("text-subtitle1")
            with ui.grid(columns=2).classes("w-full gap-2"):
                name_in = ui.input("Character name")
                rating_in = ui.select(
                    ["spicy", "mature", "explicit"], value="mature", label="Content rating"
                )
                setting_in = ui.input("Setting")
                tags_in = ui.input("Tags (space separated)")
            concept_in = ui.textarea("Concept (the core of the character)").classes("w-full")
            extra_in = ui.textarea("Extra requirements").classes("w-full")
            bio_status = ui.label("Biography: none")
            bio_upload = ui.upload(
                label="Biography .txt/.md", auto_upload=True,
                on_upload=lambda e: on_bio(e),
            ).props("no-thumbnails")

            ui.separator()
            ui.label("2 · Reference photos (up to 5)").classes("text-subtitle1")
            ui.label(
                "Full-size previews are shown below. The first photo is used as the card "
                "portrait unless you pick another."
            ).classes("text-caption opacity-70")
            photo_upload = ui.upload(
                label="Photos (PNG / JPG / WebP)",
                multiple=True,
                max_files=MAX_PHOTOS,
                auto_upload=True,
                on_multi_upload=lambda e: on_photos(e),
            ).props("no-thumbnails").classes("w-full")
            photo_gallery = ui.row().classes("w-full gap-3 items-start flex-wrap")
            portrait_select = ui.select({}, label="Portrait source").classes("w-full")
            analysis_view = ui.markdown("").classes("w-full")
            confirm_adult = ui.checkbox(
                "I confirm every person in the photos is an adult (21+) and I may use them "
                "as references"
            )

            async def on_bio(e: Any) -> None:
                state["bio"] = await e.file.text()
                bio_status.set_text(f"Biography: {e.file.name} ({len(state['bio'])} chars)")

            def photo_basename(path: str) -> str:
                return Path(path).name

            def render_photos() -> None:
                photo_gallery.clear()
                for index, path in enumerate(state["photos"], start=1):
                    with photo_gallery:
                        with ui.card().classes("w-52"):
                            ui.image(path).props("fit=contain").style(
                                "height: 240px; width: 100%;"
                            )
                            ui.label(f"{index}. {photo_basename(path)}").classes("text-caption")
                            with ui.row().classes("items-center gap-2"):
                                if state["portrait"] == path:
                                    ui.badge("portrait", color="primary")
                                ui.button(
                                    "Remove", icon="close",
                                    on_click=lambda p=path: remove_photo(p),
                                ).props("dense flat")
                portrait_select.set_options(
                    {p: photo_basename(p) for p in state["photos"]}
                )
                portrait_select.value = state["portrait"]

            def remove_photo(path: str) -> None:
                if path in state["photos"]:
                    state["photos"].remove(path)
                if state["portrait"] == path:
                    state["portrait"] = state["photos"][0] if state["photos"] else None
                state["analyses"] = []
                analysis_view.set_content("")
                render_photos()

            async def on_photos(e: Any) -> None:
                for file in e.files:
                    if len(state["photos"]) >= MAX_PHOTOS:
                        ui.notify(f"Maximum {MAX_PHOTOS} photos", type="warning")
                        break
                    suffix = Path(file.name).suffix or ".png"
                    path = uploads / f"photo_{uuid.uuid4().hex}{suffix}"
                    await file.save(path)
                    if str(path) not in state["photos"]:
                        state["photos"].append(str(path))
                if state["photos"] and not state["portrait"]:
                    state["portrait"] = state["photos"][0]
                state["analyses"] = []
                analysis_view.set_content("")
                render_photos()
                ui.notify(f"{len(state['photos'])} photo(s) ready", type="positive")

            def on_portrait_change(e: Any) -> None:
                state["portrait"] = e.value
                render_photos()

            portrait_select.on_value_change(on_portrait_change)

            async def do_analyze() -> None:
                if not state["photos"]:
                    ui.notify("Upload at least one photo", type="warning")
                    return
                if not require_ready():
                    return
                try:
                    analyses = await run.io_bound(
                        analyze_photos,
                        conn.make_client(),
                        state["photos"],
                        config["generation"],
                        confirm_adult=confirm_adult.value,
                    )
                    state["analyses"] = analyses
                    analysis_view.set_content(
                        "### Photo analysis\n" + format_analyses(analyses)
                    )
                    ui.notify("Photos analyzed", type="positive")
                except UnderageSubject as exc:
                    ui.notify(str(exc), type="negative", timeout=8000)
                except Exception as exc:
                    ui.notify(str(exc), type="negative", timeout=8000)

            ui.button("Analyze photos", icon="visibility", on_click=do_analyze)
            ui.separator()
            ui.label("3 · Generate").classes("text-subtitle1")
            gen_status = ui.label("Ready.")

            def build_args() -> SimpleNamespace:
                return SimpleNamespace(
                    concept=concept_in.value or "",
                    name=name_in.value or None,
                    setting=setting_in.value or None,
                    extra=extra_in.value or None,
                    tags=(tags_in.value or "").split() or None,
                    content_rating=rating_in.value or "mature",
                    narrative_language=None,
                    definition_language=None,
                    bio=None,
                    bio_text=state["bio"],
                    photo=None,
                    photos=list(state["photos"]),
                    portrait=state["portrait"],
                    no_photo_in_prompt=False,
                    appearance_reference=format_analyses(state["analyses"]),
                    out=config["paths"].get("output_dir", "generated"),
                    config=None,
                    interactive=False,
                    dry_run=False,
                )

            async def do_generate() -> None:
                if not concept_in.value:
                    ui.notify("Enter a concept first", type="warning")
                    return
                if state["photos"] and not confirm_adult.value:
                    ui.notify("Confirm the photo subjects are adults", type="warning")
                    return
                if not require_ready():
                    return
                gen_status.set_text("Generating — this takes a few minutes…")
                try:
                    args = build_args()
                    result = await run.io_bound(generate, args, conn.config_override(config))
                    slug = store.create(
                        result["card"],
                        result["portrait_png"],
                        bio=state["bio"],
                        photos=state["photos"],
                        analyses=state["analyses"],
                        brief=concept_in.value,
                    )
                    refresh_list()
                    select(slug)
                    m = result["metrics"]
                    gen_status.set_text(
                        f"Created {result['card']['data']['name']} — definition "
                        f"{m['definition']} chars, greeting {m['greeting']} chars. "
                        f"Set the tagline and content warnings in CT Studio."
                    )
                    ui.notify("Character created", type="positive")
                except Exception as exc:
                    gen_status.set_text(f"Error: {exc}")
                    ui.notify(str(exc), type="negative", timeout=8000)

            ui.button("Generate character", icon="auto_awesome", color="primary", on_click=do_generate)
            render_photos()

    # --------------------------------------------------------------------- card
        with ui.tab_panel(card_tab):
            card_view = ui.column().classes("w-full")

            def refresh_card() -> None:
                card_view.clear()
                if not state["slug"]:
                    with card_view:
                        ui.label("Select a generated character from the library.")
                    return
                character = store.get(state["slug"])
                data = character["card"]["data"]
                with card_view:
                    with ui.row().classes("w-full items-start gap-4"):
                        if character["portrait"]:
                            ui.image(str(character["portrait"])).props("fit=contain").style(
                                "height: 420px; width: auto;"
                            )
                        with ui.column():
                            ui.label(data.get("name", "")).classes("text-h6")
                            ui.markdown(f"**Tags:** {', '.join(data.get('tags', []))}")
                    ui.markdown("### Definition\n\n" + data.get("description", ""))
                    ui.markdown("### Greeting\n\n" + data.get("first_mes", ""))
                    ui.markdown("### Public description\n\n" + data.get("creator_notes", ""))
                    notes = "\n".join(draft_warnings(
                        {"description": data.get("description", ""), "first_mes": data.get("first_mes", "")}
                    ))
                    if notes:
                        ui.markdown("### Notes\n\n" + notes)
                    base = f"/files/{_rel(character['path'])}"
                    ui.link("Download card.json", f"{base}/card.json", new_tab=True)
                    ui.link("Download card.png", f"{base}/card.png", new_tab=True)

    refresh_list()
    refresh_card()


def main() -> None:
    config = load_config()
    build_ui(config)
    ui.run(host="127.0.0.1", port=8080, reload=False, title="Character Card Studio")


if __name__ == "__main__":
    main()
