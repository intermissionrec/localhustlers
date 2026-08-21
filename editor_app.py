#!/usr/bin/env python3
"""
Local Hustlers — content editor.

A small Streamlit app for editing the text on each page of the site
without touching HTML. It reads/writes the JSON files in content/,
regenerates the HTML via build.py when you hit "Save & rebuild", and
shows a live preview of the actual page (served by a tiny local web
server this app starts for you) so you can see the result immediately.

There's also a "Publish to GitHub" section in the sidebar that commits
and pushes your changes straight to the repo behind GitHub Pages —
see git_publish.py. That only works if this folder is your actual git
clone of that repo (the app's sidebar tells you plainly if it isn't).

For local, laptop-only use:
    pip install -r requirements.txt
    streamlit run editor_app.py
Then open the URL Streamlit prints (usually http://localhost:8501).

For running this on a VM behind a real domain (e.g.
editor.intermissionrec.com/localhustlers) with a login gate in front of
it, see deploy/Caddyfile, deploy/run_editor.sh and deploy/editor.service
instead of running the command above directly.
"""
import http.server
import os
import re
import socketserver
import threading
import uuid
from pathlib import Path

import streamlit as st

import build
import git_publish

PASSWORD_ENV_VAR = "EDITOR_PASSWORD"
PREVIEW_BASE_ENV_VAR = "PREVIEW_PUBLIC_BASE"

ROOT = build.ROOT
PREVIEW_PORT = 8642

# Uploaded photos/videos land under assets/uploads/<page>/<images|videos>/ so
# they're plain files in the repo — GitHub Pages serves them like any other
# asset, and "Publish to GitHub" picks them up the same as a content edit.
UPLOADS_DIR = ROOT / "assets" / "uploads"
IMAGE_TYPES = ["png", "jpg", "jpeg", "webp", "gif"]
VIDEO_TYPES = ["mp4", "webm", "mov"]
# GitHub hard-rejects files over 100MB. Stay comfortably under that so a
# push doesn't fail after the editor already accepted the upload.
MAX_VIDEO_BYTES = 90 * 1024 * 1024
# Where the *browser* (not this server) should reach the preview server.
# Locally this is just localhost:8642. Once this app is deployed behind a
# reverse proxy on a real domain, the browser can't reach "localhost" on
# the VM — set PREVIEW_PUBLIC_BASE to the public, proxied path instead
# (see deploy/Caddyfile), e.g.:
#   PREVIEW_PUBLIC_BASE=https://editor.intermissionrec.com/localhustlers/_preview
PREVIEW_BASE = os.environ.get(PREVIEW_BASE_ENV_VAR, f"http://localhost:{PREVIEW_PORT}")

PAGE_LABELS = {
    "index": "Начало (Home)",
    "contestants": "Участници (Contestants)",
    "episodes": "Епизоди (Episodes)",
    "about": "За нас (About)",
    "sponsors": "Спонсори (Sponsors)",
    "contacts": "Контакти (Contacts)",
}


# ---------------------------------------------------------------------------
# Live preview server — a plain static file server over the site folder,
# started once in a background thread the first time the app runs.
# ---------------------------------------------------------------------------
@st.cache_resource
def ensure_preview_server():
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def log_message(self, *args):
            pass  # keep the terminal quiet

    def _serve():
        with socketserver.ThreadingTCPServer(("127.0.0.1", PREVIEW_PORT), QuietHandler) as httpd:
            httpd.daemon_threads = True
            httpd.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return True


def show_preview(filename):
    st.caption("Live preview")
    version = st.session_state.get("preview_version", 0)
    url = f"{PREVIEW_BASE}/{filename}?v={version}"
    st.components.v1.iframe(url, height=700, scrolling=True)
    st.caption(f"Serving from {url.split('?')[0]}")


def bump_preview():
    st.session_state["preview_version"] = st.session_state.get("preview_version", 0) + 1


# ---------------------------------------------------------------------------
# Photo / video uploads
# ---------------------------------------------------------------------------
def _safe_filename(name):
    """Strip any path components and keep only filesystem-safe characters."""
    name = os.path.basename(name)
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-") or "file"
    ext = re.sub(r"[^A-Za-z0-9.]+", "", ext)
    return f"{stem}{ext}"


def _save_uploaded_file(uploaded_file, subdir):
    """Write an uploaded file under assets/uploads/<subdir>/ and return its
    path relative to the site root (what the JSON/HTML should reference)."""
    target_dir = UPLOADS_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex[:8]}_{_safe_filename(uploaded_file.name)}"
    dest = target_dir / unique_name
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str((Path("assets") / "uploads" / subdir / unique_name).as_posix())


def render_media_field(page_key, card_id, subdir, kind="image"):
    """A photo or video upload control for one card. Keeps the resolved
    relative path in session_state under f"{page_key}__card_{card_id}_{kind}",
    which render_card_list reads back when building the card dict to save."""
    path_key = f"{page_key}__card_{card_id}_{kind}"
    sig_key = f"{path_key}_sig"
    current = st.session_state.get(path_key, "")

    if kind == "image":
        label, types = "Photo", IMAGE_TYPES
    else:
        label, types = "Video", VIDEO_TYPES

    if current:
        full_path = ROOT / current
        if kind == "image" and full_path.exists():
            st.image(str(full_path), width=96)
        else:
            st.caption(f"Current {label.lower()}: `{current}`")
        if st.button(f"🗑️ Remove {label.lower()}", key=f"{path_key}_clear"):
            st.session_state[path_key] = ""
            st.session_state[sig_key] = ""
            st.rerun()

    uploaded = st.file_uploader(f"Upload {label.lower()}", type=types, key=f"{path_key}_uploader")
    if uploaded is not None:
        sig = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get(sig_key) != sig:
            if kind == "video" and uploaded.size > MAX_VIDEO_BYTES:
                st.error(
                    f"That file is {uploaded.size / 1e6:.0f}MB. GitHub rejects files over "
                    f"100MB, so keep videos under about {MAX_VIDEO_BYTES // (1024 * 1024)}MB "
                    "— compress it or trim it down and try again."
                )
            else:
                saved_path = _save_uploaded_file(uploaded, subdir)
                st.session_state[path_key] = saved_path
                st.session_state[sig_key] = sig
                st.rerun()


# ---------------------------------------------------------------------------
# Reordering cards
# ---------------------------------------------------------------------------
def _card_label(page_key, card_id):
    title = st.session_state.get(f"{page_key}__card_{card_id}_title", "").strip()
    return f"{title or 'Untitled'} #{card_id}"


def render_reorder_widget(page_key, ids_key):
    """Drag-and-drop reordering when streamlit-sortables is installed. The
    per-card ↑/↓ buttons in render_card_list always work regardless, in
    case the drag component doesn't render nicely behind a given proxy."""
    ids = st.session_state[ids_key]
    if len(ids) < 2:
        return
    try:
        from streamlit_sortables import sort_items
    except ImportError:
        st.caption(
            "Drag-to-reorder needs one more package on the server: "
            "`pip install -r requirements.txt`. Use the ↑ / ↓ buttons on "
            "each card below in the meantime."
        )
        return

    labels = [_card_label(page_key, cid) for cid in ids]
    st.caption("🔀 Drag to reorder")
    new_labels = sort_items(labels, key=f"{page_key}__sortable")
    if new_labels != labels:
        try:
            new_ids = [int(label.rsplit("#", 1)[1]) for label in new_labels]
        except (ValueError, IndexError):
            new_ids = ids  # unexpected shape — leave the order untouched
        if new_ids != ids and sorted(new_ids) == sorted(ids):
            st.session_state[ids_key] = new_ids
            st.rerun()


# ---------------------------------------------------------------------------
# Small state helpers
# ---------------------------------------------------------------------------
def load_page_once(page_key, init_fn):
    """Run init_fn(data) exactly once per page, the first time it's opened."""
    flag = f"{page_key}__loaded"
    if not st.session_state.get(flag):
        data = build.load_content(page_key)
        init_fn(data)
        st.session_state[flag] = True


def save_and_rebuild(page_key, data):
    build.save_content(page_key, data)
    build.build_page(page_key)
    bump_preview()
    st.success(f"Saved and rebuilt {build.PAGES[page_key]} ✅")


# ---------------------------------------------------------------------------
# Reusable editor for the card-grid pages (contestants / episodes)
# ---------------------------------------------------------------------------
def render_card_list(page_key, avatar_label, default_avatar, media_subdir, allow_video=False):
    """Render + save the card list. Assumes the caller already initialized
    session_state (intro fields and the card id list) for this page."""
    ids_key = f"{page_key}__card_ids"
    counter_key = f"{page_key}__card_counter"

    render_reorder_widget(page_key, ids_key)

    ids = st.session_state[ids_key]
    for position, card_id in enumerate(list(ids)):
        title_val = st.session_state.get(f"{page_key}__card_{card_id}_title", "")
        with st.expander(f"🎴 {title_val or '(untitled card)'}", expanded=False):
            c_up, c_down, c_remove = st.columns([1, 1, 4])
            with c_up:
                if st.button("↑", key=f"{page_key}__card_{card_id}_up", disabled=(position == 0)):
                    ids[position - 1], ids[position] = ids[position], ids[position - 1]
                    st.rerun()
            with c_down:
                if st.button("↓", key=f"{page_key}__card_{card_id}_down", disabled=(position == len(ids) - 1)):
                    ids[position + 1], ids[position] = ids[position], ids[position + 1]
                    st.rerun()
            with c_remove:
                if st.button("🗑️ Remove this card", key=f"{page_key}__card_{card_id}_remove"):
                    st.session_state[ids_key].remove(card_id)
                    st.rerun()

            c1, c2 = st.columns([1, 3])
            with c1:
                st.text_input(avatar_label, key=f"{page_key}__card_{card_id}_avatar")
            with c2:
                st.text_input("Title", key=f"{page_key}__card_{card_id}_title")
            st.text_input("Subtext", key=f"{page_key}__card_{card_id}_meta")

            st.markdown("---")
            render_media_field(page_key, card_id, media_subdir, kind="image")
            if allow_video:
                render_media_field(page_key, card_id, media_subdir, kind="video")

    if st.button("➕ Add a card", key=f"{page_key}__card_add"):
        new_card = {"avatar": default_avatar, "title": "", "meta": "", "image": ""}
        if allow_video:
            new_card["video"] = ""
        _add_card(page_key, ids_key, counter_key, new_card)
        st.rerun()

    if st.button("💾 Save & rebuild", key=f"{page_key}__save", type="primary"):
        cards = []
        for card_id in st.session_state[ids_key]:
            card = {
                "avatar": st.session_state[f"{page_key}__card_{card_id}_avatar"],
                "title": st.session_state[f"{page_key}__card_{card_id}_title"],
                "meta": st.session_state[f"{page_key}__card_{card_id}_meta"],
                "image": st.session_state.get(f"{page_key}__card_{card_id}_image", ""),
            }
            if allow_video:
                card["video"] = st.session_state.get(f"{page_key}__card_{card_id}_video", "")
            cards.append(card)
        data = {
            "title": st.session_state[f"{page_key}__title"],
            "meta_description": st.session_state[f"{page_key}__meta"],
            "eyebrow": st.session_state[f"{page_key}__eyebrow"],
            "page_title": st.session_state[f"{page_key}__page_title"],
            "lede": st.session_state[f"{page_key}__lede"],
            "cards": cards,
        }
        if f"{page_key}__placeholder" in st.session_state:
            data["placeholder"] = st.session_state[f"{page_key}__placeholder"]
        save_and_rebuild(page_key, data)


def _add_card(page_key, ids_key, counter_key, card):
    st.session_state[counter_key] += 1
    card_id = st.session_state[counter_key]
    st.session_state[ids_key].append(card_id)
    st.session_state[f"{page_key}__card_{card_id}_avatar"] = card.get("avatar", "")
    st.session_state[f"{page_key}__card_{card_id}_title"] = card.get("title", "")
    st.session_state[f"{page_key}__card_{card_id}_meta"] = card.get("meta", "")
    st.session_state[f"{page_key}__card_{card_id}_image"] = card.get("image", "")
    if "video" in card:
        st.session_state[f"{page_key}__card_{card_id}_video"] = card.get("video", "")


def render_intro_fields(page_key):
    """Title/meta/eyebrow/page_title/lede — shared by every page type."""
    st.text_input("Browser tab title", key=f"{page_key}__title")
    st.text_area("Meta description (SEO)", key=f"{page_key}__meta", height=68)
    st.text_input("Eyebrow (small label above the heading)", key=f"{page_key}__eyebrow")
    st.text_input("Page heading", key=f"{page_key}__page_title")
    st.text_area("Intro text", key=f"{page_key}__lede", height=100)


# ---------------------------------------------------------------------------
# Page-specific editors
# ---------------------------------------------------------------------------
def render_index():
    page_key = "index"

    def init(data):
        st.session_state[f"{page_key}__title"] = data["title"]
        st.session_state[f"{page_key}__meta"] = data["meta_description"]
        st.session_state[f"{page_key}__hero_eyebrow"] = data["hero"]["eyebrow"]
        st.session_state[f"{page_key}__hero_title"] = data["hero"]["title"]
        st.session_state[f"{page_key}__hero_subtitle"] = data["hero"]["subtitle"]
        st.session_state[f"{page_key}__hero_primary_text"] = data["hero"]["primary_btn_text"]
        st.session_state[f"{page_key}__hero_primary_href"] = data["hero"]["primary_btn_href"]
        st.session_state[f"{page_key}__hero_outline_text"] = data["hero"]["outline_btn_text"]
        st.session_state[f"{page_key}__hero_outline_href"] = data["hero"]["outline_btn_href"]
        st.session_state[f"{page_key}__about_eyebrow"] = data["about_teaser"]["eyebrow"]
        st.session_state[f"{page_key}__about_title"] = data["about_teaser"]["title"]
        st.session_state[f"{page_key}__about_lede"] = data["about_teaser"]["lede"]
        st.session_state[f"{page_key}__about_placeholder"] = data["about_teaser"]["placeholder"]

    load_page_once(page_key, init)

    st.text_input("Browser tab title", key=f"{page_key}__title")
    st.text_area("Meta description (SEO)", key=f"{page_key}__meta", height=68)

    st.markdown("**Hero section**")
    st.text_input("Eyebrow", key=f"{page_key}__hero_eyebrow")
    st.text_input("Headline", key=f"{page_key}__hero_title")
    st.text_area("Subtitle", key=f"{page_key}__hero_subtitle", height=100)
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Primary button text", key=f"{page_key}__hero_primary_text")
        st.text_input("Primary button link", key=f"{page_key}__hero_primary_href")
    with c2:
        st.text_input("Outline button text", key=f"{page_key}__hero_outline_text")
        st.text_input("Outline button link", key=f"{page_key}__hero_outline_href")

    st.markdown('**"About the show" section**')
    st.text_input("Eyebrow", key=f"{page_key}__about_eyebrow")
    st.text_input("Title", key=f"{page_key}__about_title")
    st.text_area("Lede", key=f"{page_key}__about_lede", height=100)
    st.text_input("Placeholder box text", key=f"{page_key}__about_placeholder")

    if st.button("💾 Save & rebuild", key=f"{page_key}__save", type="primary"):
        data = {
            "title": st.session_state[f"{page_key}__title"],
            "meta_description": st.session_state[f"{page_key}__meta"],
            "hero": {
                "eyebrow": st.session_state[f"{page_key}__hero_eyebrow"],
                "title": st.session_state[f"{page_key}__hero_title"],
                "subtitle": st.session_state[f"{page_key}__hero_subtitle"],
                "primary_btn_text": st.session_state[f"{page_key}__hero_primary_text"],
                "primary_btn_href": st.session_state[f"{page_key}__hero_primary_href"],
                "outline_btn_text": st.session_state[f"{page_key}__hero_outline_text"],
                "outline_btn_href": st.session_state[f"{page_key}__hero_outline_href"],
            },
            "about_teaser": {
                "eyebrow": st.session_state[f"{page_key}__about_eyebrow"],
                "title": st.session_state[f"{page_key}__about_title"],
                "lede": st.session_state[f"{page_key}__about_lede"],
                "placeholder": st.session_state[f"{page_key}__about_placeholder"],
            },
        }
        save_and_rebuild(page_key, data)


def render_simple_text_page(page_key):
    """Editor for about.html / sponsors.html — eyebrow/title/lede/placeholder."""

    def init(data):
        st.session_state[f"{page_key}__title"] = data["title"]
        st.session_state[f"{page_key}__meta"] = data["meta_description"]
        st.session_state[f"{page_key}__eyebrow"] = data["eyebrow"]
        st.session_state[f"{page_key}__page_title"] = data["page_title"]
        st.session_state[f"{page_key}__lede"] = data["lede"]
        st.session_state[f"{page_key}__placeholder"] = data["placeholder"]

    load_page_once(page_key, init)
    render_intro_fields(page_key)
    st.text_input("Placeholder box text", key=f"{page_key}__placeholder")

    if st.button("💾 Save & rebuild", key=f"{page_key}__save", type="primary"):
        data = {
            "title": st.session_state[f"{page_key}__title"],
            "meta_description": st.session_state[f"{page_key}__meta"],
            "eyebrow": st.session_state[f"{page_key}__eyebrow"],
            "page_title": st.session_state[f"{page_key}__page_title"],
            "lede": st.session_state[f"{page_key}__lede"],
            "placeholder": st.session_state[f"{page_key}__placeholder"],
        }
        save_and_rebuild(page_key, data)


def render_contacts():
    page_key = "contacts"

    def init(data):
        st.session_state[f"{page_key}__title"] = data["title"]
        st.session_state[f"{page_key}__meta"] = data["meta_description"]
        st.session_state[f"{page_key}__eyebrow"] = data["eyebrow"]
        st.session_state[f"{page_key}__page_title"] = data["page_title"]
        st.session_state[f"{page_key}__lede"] = data["lede"]
        st.session_state[f"{page_key}__email"] = data["email"]
        st.session_state[f"{page_key}__phone"] = data["phone"]
        st.session_state[f"{page_key}__location"] = data["location"]

    load_page_once(page_key, init)
    render_intro_fields(page_key)

    st.markdown("**Contact details**")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.text_input("Email", key=f"{page_key}__email")
    with c2:
        st.text_input("Phone", key=f"{page_key}__phone")
    with c3:
        st.text_input("Location", key=f"{page_key}__location")

    if st.button("💾 Save & rebuild", key=f"{page_key}__save", type="primary"):
        data = {
            "title": st.session_state[f"{page_key}__title"],
            "meta_description": st.session_state[f"{page_key}__meta"],
            "eyebrow": st.session_state[f"{page_key}__eyebrow"],
            "page_title": st.session_state[f"{page_key}__page_title"],
            "lede": st.session_state[f"{page_key}__lede"],
            "email": st.session_state[f"{page_key}__email"],
            "phone": st.session_state[f"{page_key}__phone"],
            "location": st.session_state[f"{page_key}__location"],
        }
        save_and_rebuild(page_key, data)


def render_cards_page(page_key, avatar_label, default_avatar, allow_video=False, include_placeholder=False):
    ids_key = f"{page_key}__card_ids"
    counter_key = f"{page_key}__card_counter"

    def init(data):
        st.session_state[f"{page_key}__title"] = data["title"]
        st.session_state[f"{page_key}__meta"] = data["meta_description"]
        st.session_state[f"{page_key}__eyebrow"] = data["eyebrow"]
        st.session_state[f"{page_key}__page_title"] = data["page_title"]
        st.session_state[f"{page_key}__lede"] = data["lede"]
        if include_placeholder:
            st.session_state[f"{page_key}__placeholder"] = data.get("placeholder", "")
        st.session_state[ids_key] = []
        st.session_state[counter_key] = 0
        for card in data.get("cards", []):
            _add_card(page_key, ids_key, counter_key, card)

    load_page_once(page_key, init)

    render_intro_fields(page_key)
    if include_placeholder:
        st.text_input(
            "Fallback text shown when there are no cards yet",
            key=f"{page_key}__placeholder",
        )
    st.markdown("**Cards**")
    render_card_list(page_key, avatar_label, default_avatar, media_subdir=page_key, allow_video=allow_video)


# ---------------------------------------------------------------------------
# Publish to GitHub Pages
# ---------------------------------------------------------------------------
def render_publish_sidebar():
    st.sidebar.divider()
    st.sidebar.subheader("Publish to GitHub Pages")

    if not git_publish.is_git_repo(ROOT):
        st.sidebar.warning(
            "This folder isn't a git repo, so there's nothing to publish to. "
            "Put these files inside your cloned GitHub Pages repo (the one "
            "behind your github.io site) and run the editor from there."
        )
        return

    branch = git_publish.current_branch(ROOT)
    remote = git_publish.remote_url(ROOT)
    st.sidebar.caption(f"Branch `{branch or '?'}` · remote `{remote or 'none set'}`")

    if not remote:
        st.sidebar.warning("No 'origin' remote is configured — add one before publishing.")
        return

    if git_publish.token_configured():
        st.sidebar.caption(f"🔑 Authenticating with `{git_publish.TOKEN_ENV_VAR}` (no local git login needed).")
    else:
        st.sidebar.caption(
            "Authenticating with this machine's own git credentials. "
            f"Set the `{git_publish.TOKEN_ENV_VAR}` environment variable instead "
            "to publish from a VM with no git login of its own."
        )

    changes = git_publish.status_lines(ROOT)
    if changes:
        with st.sidebar.expander(f"📝 {len(changes)} uncommitted change(s)"):
            st.code("\n".join(changes), language=None)
    else:
        st.sidebar.caption("Working tree clean — nothing new to publish yet.")

    commit_message = st.sidebar.text_input(
        "Commit message", value="Update site content", key="publish__message"
    )
    pull_first = st.sidebar.checkbox(
        "Pull latest changes first (recommended)", value=True, key="publish__pull"
    )

    if st.sidebar.button("🚀 Publish to GitHub", type="primary", key="publish__button"):
        with st.sidebar:
            with st.spinner("Publishing..."):
                ok, steps = git_publish.publish(ROOT, commit_message, pull_first)
            for label, result in steps:
                out = (result.stdout or "").strip()
                err = (result.stderr or "").strip()
                if out or err:
                    with st.expander(f"git {label}"):
                        if out:
                            st.code(out, language=None)
                        if err:
                            st.code(err, language=None)
            if ok:
                st.success("Published ✅ GitHub Pages usually takes a minute or two to update.")
            else:
                st.error("Publish failed — see the step details above.")


# ---------------------------------------------------------------------------
# Optional password gate — only kicks in if EDITOR_PASSWORD is set in the
# environment. Leave it unset for local, laptop-only use; set it whenever
# this app is reachable over a network (e.g. running on a VM), since anyone
# who can open the page can also push to your repo via the Publish button.
# ---------------------------------------------------------------------------
def require_password():
    required = os.environ.get(PASSWORD_ENV_VAR)
    if not required:
        return
    if st.session_state.get("authed"):
        return

    st.title("Local Hustlers — content editor")
    st.caption("This instance is password-protected.")
    pw = st.text_input("Password", type="password", key="login__password")
    if st.button("Unlock"):
        if pw == required:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Local Hustlers — content editor", layout="wide")
require_password()
ensure_preview_server()

st.sidebar.title("Local Hustlers")
st.sidebar.caption("Content editor")
page_key = st.sidebar.radio(
    "Page",
    list(PAGE_LABELS.keys()),
    format_func=lambda k: PAGE_LABELS[k],
)

st.sidebar.divider()
if st.sidebar.button("🔁 Rebuild every page"):
    build.build_all()
    bump_preview()
    st.sidebar.success("Rebuilt all pages")

render_publish_sidebar()

st.sidebar.divider()
st.sidebar.caption(
    "Edits are saved to content/*.json and turned into the real HTML files "
    "by build.py. Nothing changes on disk until you hit **Save & rebuild**."
)

st.title(PAGE_LABELS[page_key])

col_form, col_preview = st.columns([2, 3])

with col_form:
    if page_key == "index":
        render_index()
    elif page_key == "contestants":
        render_cards_page("contestants", "Fallback initials (used if no photo is uploaded)", "?")
    elif page_key == "episodes":
        render_cards_page("episodes", "Fallback number badge (used if no thumbnail is uploaded)", "01", allow_video=True)
    elif page_key == "sponsors":
        render_cards_page("sponsors", "Fallback initials (used if no logo is uploaded)", "?", include_placeholder=True)
    elif page_key == "about":
        render_simple_text_page(page_key)
    elif page_key == "contacts":
        render_contacts()

with col_preview:
    show_preview(build.PAGES[page_key])
