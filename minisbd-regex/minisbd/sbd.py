"""Découpage d'un paragraphe en phrases, sans modèle.

Suffisant pour les contenus de l'application (titres, descriptions,
annonces) : une phrase se termine par . ! ? ou … suivi d'un blanc, sauf après
une abréviation courante (« M. Diop », « av. Cheikh Anta Diop ») ou un
chiffre suivi d'un point dans un nombre (« 3.5 » ne contient pas de blanc
après le point, il n'est donc jamais coupé).

argostranslate découpe déjà le texte en paragraphes (retours à la ligne)
avant d'appeler sentences().
"""

import re

# Ponctuation finale, puis guillemets ou parenthèses fermants éventuels — en
# typographie française, « » est précédé d'une espace (insécable ou non).
_FIN_DE_PHRASE = re.compile(r"[.!?…]+(?:[ \u00a0\u202f]*[\"'»”’)\]])*(?=\s)")

_ABREVIATIONS = {
    "m", "mm", "mme", "mmes", "mlle", "mlles", "dr", "pr", "me", "st", "ste",
    "av", "bd", "bld", "rte", "no", "n°", "tél", "tel", "env", "cf", "ex",
    "etc", "mr", "mrs", "ms", "vs", "p", "pp", "vol", "fig", "min", "max",
}

# Au-delà, une « phrase » est recoupée sur les points-virgules pour rester
# loin de la longueur d'entrée maximale du modèle.
_LONGUEUR_MAX = 600


def _dernier_mot(segment):
    """Mot qui précède la ponctuation finale, tel qu'écrit (casse conservée)."""
    mots = re.findall(r"([\w°]+)[.!?…]*(?:[ \u00a0\u202f]*[\"'»”’)\]])*$", segment)
    return mots[-1] if mots else ""


def _est_abreviation(mot, ponctuation, suite):
    if ponctuation != ".":
        return False
    # Initiale d'un prénom : « A. Diallo ».
    if len(mot) == 1 and mot.isalpha() and mot.isupper():
        return True
    if mot.lower() not in _ABREVIATIONS:
        return False
    # « etc. » termine souvent une phrase : il ne coupe pas seulement si la
    # suite commence par une minuscule.
    if mot.lower() == "etc":
        return bool(suite) and suite.islower()
    return True


def decouper(texte):
    phrases = []
    debut = 0
    for fin in _FIN_DE_PHRASE.finditer(texte):
        segment = texte[debut:fin.end()]
        suite = texte[fin.end():].lstrip()[:1]
        if _est_abreviation(_dernier_mot(segment), fin.group(0).rstrip(" \u00a0\u202f\"'»”’)]"), suite):
            continue
        phrases.append(segment.strip())
        debut = fin.end()
    reste = texte[debut:].strip()
    if reste:
        phrases.append(reste)

    resultat = []
    for phrase in phrases:
        if len(phrase) <= _LONGUEUR_MAX:
            resultat.append(phrase)
            continue
        morceaux = [m.strip() for m in re.split(r"(?<=;)\s+", phrase) if m.strip()]
        resultat.extend(morceaux)
    return [p for p in resultat if p]


class SBDetect:
    def __init__(self, lang, use_gpu=False, max_threads=None):
        self.lang = lang

    def sentences(self, text):
        texte = "\n\n".join(text) if isinstance(text, list) else text
        if not texte or not texte.strip():
            return []
        return decouper(texte)
