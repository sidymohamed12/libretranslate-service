"""Module pymupdf factice : importable, inutilisable.

argostranslatefiles fait « import pymupdf as fitz » au chargement ; seule la
traduction de fichiers PDF s'en sert, et elle est désactivée dans ce
déploiement (LT_DISABLE_FILES_TRANSLATION=true).
"""


def __getattr__(nom):
    raise RuntimeError(
        f"pymupdf.{nom} indisponible : traduction de fichiers PDF désactivée dans l'image s390x")
