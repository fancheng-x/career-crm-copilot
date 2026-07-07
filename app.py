"""Career CRM Copilot — Streamlit entry point.

Sidebar: branded title + a polished option-menu nav + a Claude model picker.
"""
import streamlit as st
from streamlit_option_menu import option_menu

from src import db, config
from src.pages_ui import (
    home,
    assistant,
    add_note,
    import_page,
    contacts,
    applications,
    search,
    insights,
    follow_up,
)

st.set_page_config(page_title="Career CRM Copilot", page_icon="🧭", layout="wide")

# label -> (render function, bootstrap icon name)
PAGES = {
    "Home": (home.render, "house"),
    "Assistant": (assistant.render, "robot"),
    "Add Note": (add_note.render, "pencil-square"),
    "Import": (import_page.render, "upload"),
    "Contacts": (contacts.render, "person"),
    "Applications": (applications.render, "briefcase"),
    "Search": (search.render, "search"),
    "Insights": (insights.render, "lightbulb"),
    "Follow-up": (follow_up.render, "envelope"),
}

_MENU_STYLES = {
    "container": {"padding": "0.4rem 0.3rem", "background-color": "transparent"},
    "icon": {"font-size": "1rem"},
    "nav-link": {
        "font-size": "1rem",
        "font-weight": "500",
        "padding": "0.55rem 0.8rem",
        "margin": "3px 0",
        "border-radius": "8px",
        "--hover-color": "#e2eee8",
    },
    "nav-link-selected": {"background-color": "#2f8367", "font-weight": "600"},
}


def main():
    db.init_db()

    # A page can request a jump (e.g. Dashboard card → open a contact).
    target = st.session_state.pop("nav_target", None)
    manual = list(PAGES).index(target) if target in PAGES else None

    with st.sidebar:
        choice = option_menu(
            menu_title="Career CRM Copilot",
            menu_icon="compass",
            options=list(PAGES.keys()),
            icons=[icon for _, icon in PAGES.values()],
            default_index=0,
            manual_select=manual,
            key="main_menu",
            styles=_MENU_STYLES,
        )
        if target in PAGES:      # ensure routing even if the menu lags a frame
            choice = target
        st.divider()
        models = config.CLAUDE_MODELS
        cur = st.session_state.get("model_id", config.CLAUDE_MODEL)
        default_idx = models.index(cur) if cur in models else 0
        st.selectbox("Claude model", models, index=default_idx, key="model_id",
                     help="Any Claude model — switch anytime; used for all AI features.")

    PAGES[choice][0]()


if __name__ == "__main__":
    main()
