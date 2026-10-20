# libretranslate-service

Image Docker **multi-architecture** de
[LibreTranslate](https://github.com/LibreTranslate/LibreTranslate) 1.9.6 —
**linux/amd64, linux/arm64 et linux/s390x** (IBM Z / LinuxONE) — avec les
modèles **français ⇄ anglais** inclus, et des manifestes Kubernetes génériques
pour la déployer.

L'image est fournie avec des valeurs par défaut ; le déploiement (namespace,
accès, ressources) reste à adapter à chaque infrastructure.

## Selon l'architecture

| Architecture      | CTranslate2                                                             | Calcul  | Build                                           |
| ----------------- | ----------------------------------------------------------------------- | ------- | ----------------------------------------------- |
| amd64             | wheel officielle (MKL / oneDNN)                                         | int8    | quelques minutes                                |
| arm64             | wheel officielle (Ruy)                                                  | int8    | quelques minutes                                |
| s390x             | compilé depuis les sources (OpenBLAS) + modèles convertis en big-endian | float32 | ~30-60 min en natif, plusieurs heures sous QEMU |
| autres (ppc64le…) | compilé depuis les sources (OpenBLAS)                                   | float32 | non testé                                       |

Sur toutes les architectures, la traduction de fichiers (PDF, DOCX…) est
désactivée : l'image ne sert que la traduction de texte (`/translate`).

## Pourquoi pas l'image officielle

L'image officielle `libretranslate/libretranslate` n'est publiée qu'en
amd64/arm64. Sur s390x, quatre obstacles, levés par le `Dockerfile` :

| Obstacle                                                                                                                                           | Solution                                                                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **CTranslate2** (moteur d'inférence) : aucune wheel s390x                                                                                          | Compilé depuis les sources (v4.8.3) avec **OpenBLAS** (MKL est x86 seulement). Sur amd64/arm64, la wheel officielle est utilisée.                                        |
| **Boutisme** : s390x est big-endian, CTranslate2 lit `model.bin` octet pour octet sans conversion — un modèle publié (little-endian) est illisible | `scripts/ct2_big_endian.py` réécrit les modèles en big-endian **au build**. Sans effet sur une machine little-endian.                                                    |
| **minisbd** (découpage en phrases) dépend d'**onnxruntime**, sans wheel s390x                                                                      | Remplacé par `minisbd-regex/` : même API, découpage par expressions régulières (abréviations françaises, guillemets « », initiales…).                                    |
| **PyMuPDF** (traduction de PDF) : pas de wheel s390x, dépend aussi d'onnxruntime, mais importé au démarrage                                        | Remplacé par `pymupdf-desactive/` : module vide. La traduction de fichiers est désactivée (`LT_DISABLE_FILES_TRANSLATION`), seule la traduction de texte est disponible. |

Le build se termine par un **test de fumée** : une vraie traduction fr→en sur
l'architecture cible. Un modèle mal converti ou un calcul faux fait échouer
le build, pas la production.

## Ce qui a été vérifié, et ce qui reste à valider

Vérifié hors s390x :

- le convertisseur big-endian, sur des `model.bin` écrits par le sérialiseur de
  CTranslate2 4.8.3 (Transformers quantifiés int8, float16, int8_float16, plus
  float32/int16/int32 et les alias) : relecture indépendante identique, valeur
  par valeur, et idempotence ;
- le découpage en phrases (abréviations, initiales, nombres décimaux, « »,
  points de suspension) ;
- l'installation de LibreTranslate 1.9.6 avec les deux remplaçants : aucune
  trace d'onnxruntime, `pip check` sans erreur, application importable.

**Pas vérifiable sans machine s390x : la compilation de CTranslate2 et
l'exécution des calculs en big-endian.** C'est précisément ce que contrôle le
test de fumée : un premier build réussi sur le cluster vaut validation.

## Contenu

```
Dockerfile                    image pour toutes les architectures
docker-compose.yml            test en local (image officielle ou image de ce dépôt)
scripts/ct2_big_endian.py     conversion des modèles CTranslate2 en big-endian
minisbd-regex/                remplaçant de minisbd, sans onnxruntime
pymupdf-desactive/            remplaçant de PyMuPDF (traduction de PDF désactivée)
kubernetes/                   ConfigMap, Deployment, Service, NetworkPolicy (kustomize)
.github/workflows/image.yml   image multi-architecture publiée sur Docker Hub
```

## Tester en local

```bash
docker compose --profile officiel up -d            # image officielle, prête en ~2 min
# ou
docker compose --profile maison up -d --build      # l'image de ce dépôt, pour votre machine

curl -s -X POST http://localhost:5000/translate -H 'Content-Type: application/json' \
  -d '{"q":["La ligne BRT ouvre lundi."],"source":"fr","target":"en","format":"text"}'
# {"translatedText":["The BRT line opens on Monday."]}
```

L'interface web est active en local : http://localhost:5000. Les deux
profils écoutent sur le port 5000, n'en lancer qu'un à la fois. Le profil
`maison` valide le Dockerfile, les remplaçants et le test de fumée, mais sur
une machine little-endian : la conversion big-endian n'y est pas exercée.

## Construire l'image

Pour l'architecture de votre machine :

```bash
docker build -t <registre>/libretranslate-service:1.9.6 .
```

Image multi-architecture (un seul tag, chaque nœud tire sa variante) :

```bash
docker buildx build --platform linux/amd64,linux/arm64,linux/s390x \
  -t <registre>/libretranslate-service:1.9.6 --push .
```

Sous émulation QEMU, la variante s390x prend plusieurs heures ; sur une
machine s390x, la construire en natif (`docker build`) est bien plus rapide.

Via GitHub Actions : `.github/workflows/image.yml` construit chaque
architecture sur sa propre machine (amd64 et arm64 en natif, s390x sous
QEMU), puis assemble un tag unique sur Docker Hub (secrets
`DOCKERHUB_USERNAME` et `DOCKERHUB_TOKEN`), à la demande ou sur un tag `v*`.

## Déployer sur Kubernetes

```bash
# 1. Indiquer l'image dans kubernetes/kustomization.yaml (images:)
# 2. Déployer
kubectl apply -k kubernetes/ -n <namespace>
kubectl -n <namespace> rollout status deploy/libretranslate

# 3. Autoriser l'application appelante : ses pods doivent porter le label
#    libretranslate-client: "true" (ou adapter kubernetes/networkpolicy.yaml)

# 4. Essai depuis un pod autorisé
kubectl -n <namespace> exec deploy/<application> -- curl -s -X POST http://libretranslate:5000/translate \
  -H 'Content-Type: application/json' \
  -d '{"q":["Bonjour"],"source":"fr","target":"en","format":"text"}'
```

LibreTranslate reste **interne au namespace** : Service `ClusterIP`, aucun
Ingress, et la NetworkPolicy n'autorise que les pods de l'application
appelante. Aucune clé d'API n'est nécessaire dans ce cas (`LT_API_KEYS`
reste possible en complément, cf. `kubernetes/configmap.yaml`).

Le pod tourne en non-root (UID 1032), sans privilèges, sur n'importe quel
nœud Linux : avec une image multi-architecture, chaque nœud tire sa
variante. Si votre image ne contient qu'une architecture, ajoutez
`kubernetes.io/arch: <arch>` au `nodeSelector` de `kubernetes/deployment.yaml`.
Sur OpenShift, les mêmes manifestes
fonctionnent : retirer `runAsUser`, `runAsGroup` et `fsGroup` du
`securityContext` pour laisser la SCC `restricted` attribuer l'UID (l'image
est prévue pour un UID arbitraire du groupe 0).

## Options de build

| Argument                 | Défaut   | Rôle                                                                                                    |
| ------------------------ | -------- | ------------------------------------------------------------------------------------------------------- |
| `MODELES`                | `fr,en`  | Langues incluses (codes LibreTranslate, séparés par des virgules)                                       |
| `LIBRETRANSLATE_VERSION` | `v1.9.6` | Tag de LibreTranslate                                                                                   |
| `CTRANSLATE2_VERSION`    | `v4.8.3` | Version de CTranslate2 (doit rester en 4.x)                                                             |
| `CTRANSLATE2_SOURCE`     | `auto`   | `auto` : wheel sur amd64/arm64, compilation ailleurs ; `wheel` ou `source` pour forcer                  |
| `CTRANSLATE2_WITH_RUY`   | `OFF`    | En compilation seulement : calculs int8 via Ruy (plus rapides, moins de mémoire) — non validé sur s390x |

## Dimensionnement

- Par processus gunicorn (`LT_THREADS=2`) : ~400 Mo sur s390x (float32),
  sensiblement moins sur amd64/arm64 (int8). Requête 1,5 Gi, limite 3 Gi :
  valable partout, réductible sur amd64/arm64.
- Une seule réplique suffit si l'application appelante met les traductions en
  cache plutôt que de rappeler LibreTranslate à chaque lecture.

## Utilisé par CETUD Mobilités

Le back Spring de CETUD Mobilités appelle ce service pour servir en anglais
ses actualités, infos et sites touristiques aux clients qui envoient
`Accept-Language: en`. Chaque texte n'est traduit qu'une fois (table
`traductions`) ; si LibreTranslate est indisponible, le français est servi.
Côté back : `TRADUCTION_ACTIF=true`, `TRADUCTION_BASE_URL=http://libretranslate:5000`,
avec `TRADUCTION_TAILLE_LOT` ≤ `LT_BATCH_LIMIT` et `TRADUCTION_LONGUEUR_MAX`
≤ `LT_CHAR_LIMIT`.

## Licence

LibreTranslate est distribué sous licence AGPL-3.0, CTranslate2 sous licence
MIT ; les modèles Argos Translate ont leurs propres licences, indiquées dans
leurs métadonnées (`metadata.json` de chaque modèle installé).
