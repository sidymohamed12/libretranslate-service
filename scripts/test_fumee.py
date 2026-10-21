"""Test de fumée du build : une vraie traduction fr→en sur l'architecture cible.

Un modèle mal converti (boutisme, s390x) ou un calcul faux (OpenBLAS) fait
échouer le build plutôt que la production.
"""
import sys

import argostranslate.translate as traduction

texte = "Bonjour. La nouvelle ligne de bus ouvre lundi."
resultat = traduction.translate(texte, "fr", "en")
print("fr→en :", resultat)

minuscules = resultat.lower()
if "bus" not in minuscules or not ("monday" in minuscules or "opens" in minuscules):
    sys.exit(f"Traduction inattendue : {resultat!r}")
