"""Shared test setup."""

import os

# A missing translation key raises in tests instead of showing the key (app/i18n.py).
os.environ.setdefault("I18N_STRICT", "1")
