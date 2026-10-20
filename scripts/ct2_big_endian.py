#!/usr/bin/env python3
"""Convertit les modèles CTranslate2 (model.bin) au boutisme de la machine.

Pourquoi
--------
IBM LinuxONE (s390x) est big-endian. CTranslate2 lit model.bin octet pour
octet, sans conversion (src/models/model.cc, consume<T>) : sur s390x, un
modèle publié (écrit sur x86/ARM, little-endian) est illisible — dès le
premier entier, la « binary version » lue est aberrante et le chargement
échoue. Les modèles Argos de LibreTranslate sont dans ce cas.

Ce script réécrit model.bin en big-endian : chaque entier de l'en-tête et
chaque valeur des tenseurs est permuté selon la taille de son type. Les
autres fichiers d'un modèle (config.json, vocabulaires, sentencepiece.model)
sont du texte ou du protobuf, indépendants du boutisme.

Format de model.bin (python/ctranslate2/specs/model_spec.py, _serialize) :
  uint32 binary_version
  [v>=2] string spec ; uint32 spec_revision
  uint32 nombre_de_variables
  pour chaque variable :
    string nom ; uint8 rang ; uint32[rang] dimensions
    [v>=4] uint8 type_id ; uint32 nombre_d_octets
    [v<4]  uint8 taille_d_element ; uint32 nombre_d_elements
    octets du tenseur
  [v>=3] uint32 nombre_d_alias ; pour chaque alias : string alias ; string nom
  string = uint16 longueur (NUL final compris) + octets UTF-8 + NUL

Utilisation
-----------
  ct2_big_endian.py RACINE [RACINE...]   # cherche les model.bin sous RACINE
  ct2_big_endian.py --verifier RACINE    # contrôle sans rien écrire

Idempotent : un fichier « model.bin.big-endian » marque un modèle converti.
Sur une machine little-endian, ne fait rien (sauf --forcer, pour les tests).
"""

import argparse
import array
import os
import struct
import sys
import tempfile

VERSION_BINAIRE_MAX = 6
MARQUEUR = ".big-endian"
TAILLE_BLOC = 16 * 1024 * 1024

# DataType de CTranslate2 (include/ctranslate2/types.h) -> taille d'un élément.
TAILLE_PAR_TYPE = {
    0: 4,  # FLOAT32
    1: 1,  # INT8
    2: 2,  # INT16
    3: 4,  # INT32
    4: 2,  # FLOAT16
    5: 2,  # BFLOAT16
}


class ModeleInvalide(Exception):
    pass


class Lecteur:
    """Lit model.bin en little-endian et recopie chaque champ en big-endian."""

    def __init__(self, source, destination):
        self.source = source
        self.destination = destination

    def _lire(self, taille):
        donnees = self.source.read(taille)
        if len(donnees) != taille:
            raise ModeleInvalide(f"fin de fichier inattendue ({len(donnees)}/{taille} octets)")
        return donnees

    def entier(self, format_struct):
        taille = struct.calcsize("<" + format_struct)
        (valeur,) = struct.unpack("<" + format_struct, self._lire(taille))
        if self.destination is not None:
            self.destination.write(struct.pack(">" + format_struct, valeur))
        return valeur

    def chaine(self):
        longueur = self.entier("H")
        if longueur == 0:
            raise ModeleInvalide("chaîne de longueur nulle")
        octets = self._lire(longueur)
        if self.destination is not None:
            self.destination.write(octets)
        return octets[:-1].decode("utf-8")

    def tenseur(self, nombre_octets, taille_element):
        if taille_element not in (1, 2, 4, 8) or nombre_octets % taille_element:
            raise ModeleInvalide(f"taille d'élément {taille_element} incompatible avec {nombre_octets} octets")
        code = _code_array(taille_element)
        restant = nombre_octets
        bloc_max = TAILLE_BLOC - TAILLE_BLOC % taille_element
        while restant:
            bloc = self._lire(min(restant, bloc_max))
            if self.destination is not None:
                if taille_element == 1:
                    self.destination.write(bloc)
                else:
                    valeurs = array.array(code)
                    valeurs.frombytes(bloc)
                    valeurs.byteswap()
                    self.destination.write(valeurs.tobytes())
            restant -= len(bloc)

    def fin(self):
        if self.source.read(1):
            raise ModeleInvalide("octets inattendus après les alias")


def _code_array(taille):
    for code in ("B", "H", "I", "L", "Q"):
        if array.array(code).itemsize == taille:
            return code
    raise ModeleInvalide(f"aucun type array de {taille} octets")


def parcourir(lecteur):
    """Parcourt (et recopie) tout le fichier ; rend un résumé du modèle."""
    version = lecteur.entier("I")
    if not 1 <= version <= VERSION_BINAIRE_MAX:
        raise ModeleInvalide(
            f"version binaire {version} inconnue (fichier déjà big-endian, ou format plus récent que "
            f"{VERSION_BINAIRE_MAX})")
    spec = ""
    if version >= 2:
        spec = lecteur.chaine()
        lecteur.entier("I")
    nombre = lecteur.entier("I")
    for _ in range(nombre):
        nom = lecteur.chaine()
        rang = lecteur.entier("B")
        elements = 1
        for _ in range(rang):
            elements *= lecteur.entier("I")
        if version >= 4:
            type_id = lecteur.entier("B")
            if type_id not in TAILLE_PAR_TYPE:
                raise ModeleInvalide(f"{nom} : type {type_id} inconnu")
            taille = TAILLE_PAR_TYPE[type_id]
            nombre_octets = lecteur.entier("I")
        else:
            taille = lecteur.entier("B")
            nombre_octets = lecteur.entier("I") * taille
        if nombre_octets != elements * taille:
            raise ModeleInvalide(f"{nom} : {nombre_octets} octets pour {elements} éléments de {taille} octets")
        lecteur.tenseur(nombre_octets, taille)
    alias = 0
    if version >= 3:
        alias = lecteur.entier("I")
        for _ in range(alias):
            lecteur.chaine()
            lecteur.chaine()
    lecteur.fin()
    return {"version": version, "spec": spec, "variables": nombre, "alias": alias}


def convertir(chemin, verifier_seulement=False):
    marqueur = chemin + MARQUEUR
    if os.path.exists(marqueur):
        print(f"[déjà converti] {chemin}")
        return False
    with open(chemin, "rb") as source:
        if verifier_seulement:
            resume = parcourir(Lecteur(source, None))
            print(f"[valide, little-endian] {chemin} : {resume}")
            return False
        dossier = os.path.dirname(os.path.abspath(chemin))
        descripteur, temporaire = tempfile.mkstemp(prefix=".model.bin.", dir=dossier)
        try:
            with os.fdopen(descripteur, "wb") as destination:
                resume = parcourir(Lecteur(source, destination))
            os.chmod(temporaire, os.stat(chemin).st_mode)
            os.replace(temporaire, chemin)
        except BaseException:
            os.unlink(temporaire)
            raise
    with open(marqueur, "w", encoding="utf-8") as fichier:
        fichier.write("model.bin converti en big-endian par ct2_big_endian.py\n")
    print(f"[converti] {chemin} : {resume}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("racines", nargs="+", help="dossiers où chercher les model.bin")
    parser.add_argument("--verifier", action="store_true", help="contrôle le format sans rien écrire")
    parser.add_argument("--forcer", action="store_true",
                        help="convertit même sur une machine little-endian (tests uniquement)")
    args = parser.parse_args()

    if sys.byteorder != "big" and not (args.forcer or args.verifier):
        print(f"Machine {sys.byteorder}-endian : aucune conversion nécessaire.")
        return 0

    modeles = []
    for racine in args.racines:
        for dossier, _, fichiers in os.walk(racine):
            if "model.bin" in fichiers:
                modeles.append(os.path.join(dossier, "model.bin"))
    if not modeles:
        print("Aucun model.bin trouvé sous " + ", ".join(args.racines), file=sys.stderr)
        return 1

    for modele in sorted(modeles):
        try:
            convertir(modele, args.verifier)
        except ModeleInvalide as erreur:
            print(f"[ERREUR] {modele} : {erreur}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
