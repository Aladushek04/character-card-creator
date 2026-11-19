"""NiceGUI web interface for the character studio."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nicegui import app, run, ui

from cardgen.cli import load_config
from cardgen.client import LlamaClient
from cardgen.generator import generate
from service.chat import ChatEngine
from service.photo import UnderageSubject, analyze_photo, format_analysis
from service.store import CharacterStore

ROOT = Path(__file__).resolve().parent.parent


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_ui(config: dict[str, Any]) -> None:
    store = CharacterStore(config["paths"].get("characters_dir", "characters"))
    server = config["server"]
    client = LlamaClient(server["base_url"], server["model"], server["timeout_s"])
    engine = ChatEngine(store, client, config)
    uploads = ROOT / config["paths"].get("uploads_dir", "uploads")
    uploads.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/files", str(ROOT))

    state: dict[str, Any] = {
        "slug": None,
        "bio": "",
        "photo": None,
        "analysis": None,
        "chat_image": None,
    }

    with ui.header(elevated=True).classes("items-center"):
        ui.label("Character Card Studio").classes("text-h6")
        ui.label("local · one character = one chat").classes("ml-4 text-caption opacity-70")

    tabs = ui.tabs()
    with tabs:
        create_tab = ui.tab("Create")
        chat_tab = ui.tab("Chat")
        card_tab = ui.tab("Card")
    panels = ui.tab_panels(tabs, value=create_tab)

    # ------------------------------------------------------------------ sidebar
    with ui.left_drawer().classes("w-72"):
        ui.label("Library").classes("text-subtitle1")
        ui.label("Select a character to open its own chat.").classes("text-caption opacity-70")
        char_list = ui.column().classes("w-full")

        async def on_import(e: Any) -> None:
            data = await e.content.read()
            path = uploads / f"import_{uuid.uuid4().hex}{Path(e.name).suffix or '.png'}"
            path.write_bytes(data)
            try:
                slug = store.import_card(path)
                refresh_list()
                select(slug)
                ui.notify("Card imported")
            except Exception as exc:
                ui.notify(str(exc), type="negative")

        ui.upload(label="Import card PNG/JSON", auto_upload=True, on_upload=on_import).classes("w-full")

        def refresh_list() -> None:
            char_list.clear()
            with char_list:
                for item in store.list():
                    active = item["slug"] == state["slug"]
                    ui.button(
                        f"{item['name']}  ·  {item['messages']} msg",
                        on_click=lambda s=item["slug"]: select(s),
                    ).props("flat" if not active else "outline").classes("w-full text-left")

        def select(slug: str) -> None:
            state["slug"] = slug
            refresh_list()
            refresh_chat()
            refresh_card()
            chat_title.set_text(f"Chat: {store.get(slug)['card']['data'].get('name', slug)}")

    # ------------------------------------------------------------------- create
    with panels:
        with ui.tab_panel(create_tab):
            ui.label("1 · Reference material").classes("text-subtitle1")
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
            photo_status = ui.label("Photo: none")

            async def on_bio(e: Any) -> None:
                raw = await e.content.read()
                state["bio"] = raw.decode("utf-8", errors="replace")
                bio_status.set_text(f"Biography: {e.name} ({len(state['bio'])} chars)")

            async def on_photo(e: Any) -> None:
                raw = await e.content.read()
                suffix = Path(e.name).suffix or ".png"
                path = uploads / f"photo_{uuid.uuid4().hex}{suffix}"
                path.write_bytes(raw)
                state["photo"] = str(path)
                state["analysis"] = None
                photo_status.set_text(f"Photo: {e.name}")
                preview.clear()
                with preview:
                    ui.image(str(path)).classes("w-40")

            with ui.row().classes("w-full gap-4"):
                ui.upload(label="Biography .txt/.md", auto_upload=True, on_upload=on_bio)
                ui.upload(label="Photo (appearance reference)", auto_upload=True, on_upload=on_photo)
            confirm_adult = ui.checkbox(
                "I confirm every person in the photo is an adult (21+) and I may use it as a reference"
            )
            preview = ui.row()
            analysis_view = ui.markdown("").classes("w-full")

            async def do_analyze() -> None:
                if not state["photo"]:
                    ui.notify("Upload a photo first", type="warning")
                    return
                try:
                    state["analysis"] = await run.io_bound(
                        analyze_photo,
                        client,
                        state["photo"],
                        config["generation"],
                        confirm_adult=confirm_adult.value,
                    )
                    analysis_view.set_content(
                        "### Photo analysis\n```json\n"
                        + __import__("json").dumps(state["analysis"], ensure_ascii=False, indent=2)
                        + "\n```"
                    )
                    ui.notify("Photo analyzed")
                except UnderageSubject as exc:
                    ui.notify(str(exc), type="negative", timeout=8000)
                except Exception as exc:
                    ui.notify(str(exc), type="negative")

            ui.button("Analyze photo", icon="visibility", on_click=do_analyze)

            ui.separator()
            ui.label("2 · Generate").classes("text-subtitle1")
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
                    photo=state["photo"],
                    portrait=None,
                    no_photo_in_prompt=False,
                    appearance_reference=format_analysis(state["analysis"]),
                    out=config["paths"].get("output_dir", "generated"),
                    config=None,
                    interactive=False,
                    dry_run=False,
                )

            async def do_generate() -> None:
                if not concept_in.value:
                    ui.notify("Enter a concept first", type="warning")
                    return
                if state["photo"] and not confirm_adult.value:
                    ui.notify("Confirm the photo subject is an adult", type="warning")
                    return
                gen_status.set_text("Generating — this takes a few minutes on 16 GB VRAM…")
                try:
                    args = build_args()
                    result = await run.io_bound(generate, args, config)
                    slug = store.create(
                        result["card"],
                        result["portrait_png"],
                        bio=state["bio"],
                        photo=state["photo"],
                        analysis=state["analysis"],
                        brief=concept_in.value,
                    )
                    refresh_list()
                    select(slug)
                    m = result["metrics"]
                    gen_status.set_text(
                        f"Created {result['card']['data']['name']} — "
                        f"definition {m['definition']} chars, greeting {m['greeting']} chars. "
                        f"Set the tagline and content warnings in CT Studio."
                    )
                    ui.notify("Character created", type="positive")
                except Exception as exc:
                    gen_status.set_text(f"Error: {exc}")
                    ui.notify(str(exc), type="negative", timeout=8000)

            ui.button("Generate character", icon="auto_awesome", color="primary", on_click=do_generate)

        # ------------------------------------------------------------------ chat
        with ui.tab_panel(chat_tab):
            chat_title = ui.label("Select a character from the library.").classes("text-subtitle1")
            ui.label(
                "Each character owns a separate chat history. Switching characters never mixes context."
            ).classes("text-caption opacity-70")
            chat_history = ui.column().classes("w-full")

            def refresh_chat() -> None:
                chat_history.clear()
                if not state["slug"]:
                    return
                for message in store.get(state["slug"])["chat"]:
                    with chat_history:
                        ui.chat_message(
                            text=message.get("content", ""),
                            sent=message.get("role") == "user",
                            name="You" if message.get("role") == "user" else store.get(state["slug"])["card"]["data"]["name"],
                        )

            chat_input = ui.textarea("Your message").classes("w-full")
            chat_status = ui.label("")

            async def on_chat_photo(e: Any) -> None:
                raw = await e.content.read()
                suffix = Path(e.name).suffix or ".png"
                path = uploads / f"chat_{uuid.uuid4().hex}{suffix}"
                path.write_bytes(raw)
                state["chat_image"] = str(path)
                ui.notify("Image attached to next message")

            async def send_message() -> None:
                if not state["slug"]:
                    ui.notify("Select a character first", type="warning")
                    return
                text = (chat_input.value or "").strip()
                if not text:
                    return
                chat_input.value = ""
                chat_status.set_text("Thinking…")
                try:
                    await run.io_bound(engine.send, state["slug"], text, state["chat_image"])
                    state["chat_image"] = None
                    refresh_chat()
                    chat_status.set_text("")
                except Exception as exc:
                    chat_status.set_text(f"Error: {exc}")
                    ui.notify(str(exc), type="negative")

            with ui.row().classes("w-full items-center"):
                ui.button("Send", icon="send", on_click=send_message)
                ui.upload(label="Attach image", auto_upload=True, on_upload=on_chat_photo)
                ui.button(
                    "Clear chat",
                    icon="delete",
                    color="negative",
                    on_click=lambda: (
                        store.clear_chat(state["slug"]) if state["slug"] else None,
                        refresh_chat(),
                    ),
                )

        # ------------------------------------------------------------------- card
        with ui.tab_panel(card_tab):
            card_view = ui.column().classes("w-full")

            def refresh_card() -> None:
                card_view.clear()
                if not state["slug"]:
                    with card_view:
                        ui.label("Select a character from the library.")
                    return
                character = store.get(state["slug"])
                data = character["card"]["data"]
                with card_view:
                    with ui.row().classes("w-full items-start gap-4"):
                        if character["portrait"]:
                            ui.image(str(character["portrait"])).classes("w-40")
                        with ui.column():
                            ui.label(data.get("name", "")).classes("text-h6")
                            ui.markdown(f"**Tags:** {', '.join(data.get('tags', []))}")
                            ui.label(f"Card tokens: {character['meta'].get('tokens', 'unknown')}")
                    ui.markdown("### Definition\n\n" + data.get("description", ""))
                    ui.markdown("### Greeting\n\n" + data.get("first_mes", ""))
                    ui.markdown("### Public description\n\n" + data.get("creator_notes", ""))
                    base = f"/files/{_rel(character['path'])}"
                    ui.link("Download card.json", f"{base}/card.json", new_tab=True)
                    ui.link("Download card.png", f"{base}/card.png", new_tab=True)

    refresh_list()


def main() -> None:
    config = load_config()
    build_ui(config)
    ui.run(host="127.0.0.1", port=8080, reload=False, title="Character Card Studio")


if __name__ == "__main__":
    main()
