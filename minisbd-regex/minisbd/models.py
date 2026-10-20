"""Aucun modèle à télécharger : le découpage se fait par expressions régulières."""

# Affecté par argostranslate (settings.data_dir / "minisbd") ; inutilisé ici.
cache_dir = None

# Langues pour lesquelles argostranslate n'affichera pas d'avertissement de
# repli ; le découpage est le même pour toutes les langues à alphabet latin.
_LANGUES = ["en", "fr", "es", "pt", "it", "de", "nl", "ar", "wo"]


def list_models():
    return list(_LANGUES)


def download_models(load_only_lang_codes=None, log=None):
    if log is not None:
        log("minisbd (regex) : aucun modèle à télécharger")
