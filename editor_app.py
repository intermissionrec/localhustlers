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
import socketserver
import threading

import streamlit as st

import build
import git_publish

PASSWORD_ENV_VAR = "EDITOR_PASSWORD"
PREVIEW_BASE_ENV_VAR = "PREVIEW_PUBLIC_BASE"

ROOT = build.ROOT
PREVIEW_PORT = 8642
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
def render_card_list(page_key, avatar_label, default_avatar):
    """Render + save the card list. Assumes the caller already initialized
    session_state (intro fields and the card id list) for this page."""
    ids_key = f"{page_key}__card_ids"
    counter_key = f"{page_key}__card_counter"

    for card_id in list(st.session_state[ids_key]):
        title_val = st.session_state.get(f"{page_key}__card_{card_id}_title", "")
        with st.expander(f"🎴 {title_val or '(untitled card)'}", expanded=False):
            c1, c2 = st.columns([1, 3])
            with c1:
                st.text_input(avatar_label, key=f"{page_key}__card_{card_id}_avatar")
            with c2:
                st.text_input("Title", key=f"{page_key}__card_{card_id}_title")
            st.text_input("Subtext", key=f"{page_key}__card_{card_id}_meta")
            if st.button("🗑️ Remove this card", key=f"{page_key}__card_{card_id}_remove"):
                st.session_state[ids_key].remove(card_id)
                st.rerun()

    if st.button("➕ Add a card", key=f"{page_key}__card_add"):
        _add_card(page_key, ids_key, counter_key, {"avatar": default_avatar, "title": "", "meta": ""})
        st.rerun()

    if st.button("💾 Save & rebuild", key=f"{page_key}__save", type="primary"):
        cards = []
        for card_id in st.session_state[ids_key]:
            cards.append(
                {
                    "avatar": st.session_state[f"{page_key}__card_{card_id}_avatar"],
                    "title": st.session_state[f"{page_key}__card_{card_id}_title"],
                    "meta": st.session_state[f"{page_key}__card_{card_id}_meta"],
                }
            )
        data = {
            "title": st.session_state[f"{page_key}__title"],
            "meta_description": st.session_state[f"{page_key}__meta"],
            "eyebrow": st.session_state[f"{page_key}__eyebrow"],
            "page_title": st.session_state[f"{page_key}__page_title"],
            "lede": st.session_state[f"{page_key}__lede"],
            "cards": cards,
        }
        save_and_rebuild(page_key, data)


def _add_card(page_key, ids_key, counter_key, card):
    st.session_state[counter_key] += 1
    card_id = st.session_state[counter_key]
    st.session_state[ids_key].append(card_id)
    st.session_state[f"{page_key}__card_{card_id}_avatar"] = card["avatar"]
    st.session_state[f"{page_key}__card_{card_id}_title"] = card["title"]
    st.session_state[f"{page_key}__card_{card_id}_meta"] = card["meta"]


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


def render_cards_page(page_key, avatar_label, default_avatar):
    ids_key = f"{page_key}__card_ids"
    counter_key = f"{page_key}__card_counter"

    def init(data):
        st.session_state[f"{page_key}__title"] = data["title"]
        st.session_state[f"{page_key}__meta"] = data["meta_description"]
        st.session_state[f"{page_key}__eyebrow"] = data["eyebrow"]
        st.session_state[f"{page_key}__page_title"] = data["page_title"]
        st.session_state[f"{page_key}__lede"] = data["lede"]
        st.session_state[ids_key] = []
        st.session_state[counter_key] = 0
        for card in data["cards"]:
            _add_card(page_key, ids_key, counter_key, card)

    load_page_once(page_key, init)

    render_intro_fields(page_key)
    st.markdown("**Cards**")
    render_card_list(page_key, avatar_label, default_avatar)


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
        render_cards_page("contestants", "Avatar text (e.g. initials, or \"?\")", "?")
    elif page_key == "episodes":
        render_cards_page("episodes", "Number badge (e.g. 01)", "01")
    elif page_key in ("about", "sponsors"):
        render_simple_text_page(page_key)
    elif page_key == "contacts":
        render_contacts()

with col_preview:
    show_preview(build.PAGES[page_key])
