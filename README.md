# kaxolax-texlive-images

Images Docker TeX Live utilisées par le sandbox de compilation de **Kaxolax**.

| Variante | Usage                          | Architecture             | Tag                    |
| -------- | ------------------------------ | ------------------------ | ---------------------- |
| `medium` | développement local (WSL2)     | amd64                    | `kaxolax-texlive:2026-medium` |
| `full`   | worker de staging (c7g.large)  | arm64                    | `kaxolax-texlive:2026-full`   |

Contenu de l'image :

- Debian trixie slim (épinglée par digest) et TeX Live installé par `install-tl`, l'année étant un argument de build.
- `medium` = `scheme-medium` + `collection-latexextra` + `collection-bibtexextra` + `collection-fontsrecommended`.
- pdflatex, xelatex, lualatex, bibtex, biber, latexmk et synctex.
- Polices Noto (dont CJK) et Liberation pour XeLaTeX et LuaLaTeX. Les polices OpenType de TeX Live sont visibles par fontconfig.
- `texmf.cnf` durci (`openin_any = p`, `openout_any = p`, `shell_escape = f`).
- Utilisateur UID 1000, `HOME=/tmp`. Caches de polices (fontconfig, luaotfload) construits au build.
- La suite de tests malveillants est copiée dans `/usr/share/kaxolax/malicious`, pour que l'agent de compilation la rejoue.
- L'index des packages TeX Live de l'image est dans `/usr/share/kaxolax/packages.json` (voir « Index des packages »).

## Prérequis

- Docker (Docker Desktop avec l'intégration WSL2 sous Windows) ;
- Python 3 (tests) ;
- pour tester sous gVisor : `sudo GVISOR_RELEASE=20260928.0 scripts/install-gvisor.sh` (Linux uniquement).

## Construire

```bash
docker build --build-arg TEXLIVE_YEAR=2026 --build-arg TEXLIVE_SCHEME=medium -t kaxolax-texlive:2026-medium .
```

Comptez environ 15 minutes pour `medium` et plus d'une heure pour `full`. `TEXLIVE_REPOSITORY`
permet d'imposer un miroir CTAN précis. Par défaut, l'installeur utilise l'archive historique
figée pour une année terminée, sinon `mirror.ctan.org`.

L'image `medium` est aussi publiée sur GHCR à chaque build de `main` :

```bash
docker pull ghcr.io/synapsbranch-ux/kaxolax-texlive:2026-medium
docker tag ghcr.io/synapsbranch-ux/kaxolax-texlive:2026-medium kaxolax-texlive:2026-medium
```

## Tester

Chaque cas lance un conteneur neuf avec exactement les règles du sandbox de l'agent :

- `--network none`, UID 1000, `--read-only`, `/tmp` en tmpfs `noexec` ;
- `--cap-drop ALL`, `no-new-privileges` ;
- 2 Go de mémoire, 1 CPU, 256 processus ;
- `RLIMIT_FSIZE` à 101 Mo (le plafond du PDF est de 100 Mo) ;
- timeout suivi de `docker kill`.

```bash
python3 tests/run_cases.py --image kaxolax-texlive:2026-medium tests/smoke tests/malicious
python3 tests/run_cases.py --image kaxolax-texlive:2026-medium --runtime runsc tests/malicious   # gVisor
python3 tests/run_cases.py --image kaxolax-texlive:2026-medium --only lua tests/malicious        # filtre
```

### Suite de tests malveillants (`tests/malicious`)

Chaque cas doit échouer proprement, sans rien laisser fuiter :

| Cas                                         | Attaque                                               | Ce qui la bloque                                           |
| ------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------- |
| `read-passwd-input`, `-traversal`, `-openin` | lire `/etc/passwd` par `\input`, `../..`, `\openin`   | fichier illisible pour l'UID 1000 (voir ci-dessous)        |
| `read-host-file`, `lua-read-host-file`      | lire un fichier de l'hôte par chemin absolu (TeX, Lua) | isolation du conteneur : seul le répertoire de travail est monté |
| `write18`                                   | `\write18`, `\input\|cmd`                             | `shell_escape = f`                                         |
| `openout-parent`, `-absolute`, `-hidden`    | écrire vers `../`, `/tmp`, un fichier caché           | `openout_any = p`                                          |
| `lua-write-escape`                          | écrire hors du répertoire par `io.open`               | `openout_any = p` (appliqué par LuaTeX), racine en lecture seule |
| `lua-network`                               | réseau depuis `\directlua`, `io.popen`, `os.execute`  | LuaSocket et commandes désactivés, `--network none`        |
| `lua-read-passwd`                           | lire `/etc/passwd` par `io.open`                      | fichier illisible pour l'UID 1000                          |
| `infinite-loop`                             | boucle infinie                                        | timeout imposé puis `docker kill`                          |
| `huge-pdf`                                  | PDF démesuré (20 000 pages)                           | `RLIMIT_FSIZE`, statut `error` au-delà de 100 Mo           |
| `latexmkrc-perl`                            | `latexmkrc` (Perl) fourni par le projet               | `latexmk -norc`                                            |
| `project-texmf-cnf`                         | `texmf.cnf` du projet qui réactive shell escape       | le répertoire courant n'est pas dans `TEXMFCNF`            |
| `bibtex-absolute`, `biber-absolute`         | base bibliographique `/etc/passwd`                    | fichier illisible pour l'UID 1000                          |

**Attention, TeX Live 2026 :** `openin_any` n'a plus aucun effet. TeX Live l'a supprimé en
décembre 2025 (voir les commentaires de `texmf-dist/web2c/texmf.cnf`). TeX et Lua peuvent donc
lire tout fichier présent dans l'image. La protection en lecture repose sur deux points :

- l'isolation du conteneur : seul le répertoire de travail du projet est monté, et rien de sensible ne se trouve dans l'image ;
- `/etc/passwd` et `/etc/group` sont illisibles pour l'UID 1000.

La valeur `openin_any = p` reste dans `texmf.cnf` : elle est sans effet, mais elle s'appliquerait
à une année antérieure.

## Index des packages

`scripts/package-index.py` (Python 3, bibliothèque standard seule) lit la base des paquets de
TeX Live (`texlive.tlpdb`) et écrit un index JSON trié et déterministe, sans date. Il sert au
gestionnaire de packages de l'éditeur (recherche, ajout d'un `\usepackage`, correction d'une
erreur « File `xyz.sty' not found »).

Le Dockerfile le génère au build dans une étape `index` jetable, depuis la base de l'installation
(`/usr/local/texlive/<année>/tlpkg/texlive.tlpdb`) : python3 n'entre pas dans l'image finale, qui ne
reçoit que `/usr/share/kaxolax/packages.json`. Le build échoue si l'année de la base diffère de
`TEXLIVE_YEAR`, s'il y a moins de 1 000 packages, ou si `amsmath.sty`, `graphicx.sty`,
`hyperref.sty` ou `scrartcl.cls` (koma-script, de catégorie `TLCore`) manquent.

```bash
python3 scripts/package-index.py /usr/local/texlive/2026/tlpkg/texlive.tlpdb -o packages.json
python3 scripts/package-index.py texlive.tlpdb.xz --pretty    # xz accepté, ou l'entrée standard
docker run --rm kaxolax-texlive:2026-medium cat /usr/share/kaxolax/packages.json > packages.json
python3 -m unittest discover -s tests -p 'test_*.py'          # fixture : tests/fixtures/texlive.tlpdb
```

Format (listes abrégées) :

```json
{
  "texliveYear": 2026,
  "generatedFrom": "texlive.tlpdb",
  "packages": [
    {
      "name": "pgf",
      "shortdesc": "Create PostScript and PDF graphics in TeX",
      "category": "Package",
      "topics": ["graphics", "graphics-in-tex", "pgf-tikz", "tagged-pdf-partially"],
      "license": "lppl1.3c gpl2 fdl",
      "version": "3.1.12",
      "ctanUrl": "https://ctan.org/pkg/pgf",
      "docUrl": "https://texdoc.org/pkg/pgf",
      "styles": ["pgf.sty", "pgfcore.sty", "pgfkeys.sty", "pgfrcs.sty", "tikz.sty", "xxcolor.sty"],
      "collection": "collection-pictures"
    }
  ],
  "byStyle": { "graphicx.sty": ["graphics"], "tikz.sty": ["pgf"] }
}
```

- Paquets retenus, triés par nom : catégories `Package` et `ConTeXt`, et paquets `TLCore` qui ont
  une fiche au catalogue CTAN ou fournissent un `.sty`/`.cls`. TeX Live range en `TLCore` de vrais
  packages LaTeX (`koma-script` : `scrartcl.cls`, `typearea.sty`, `scrlayer-scrpage.sty`… ;
  `dvips`, `asymptote`) et les moteurs (`xetex`, `pdftex`) ; `category` garde la valeur de la base.
  Exclus : paquets d'architecture (`latexmk.x86_64-linux`), `00texlive.*`, le reste de `TLCore`
  (`texlive.infra`, `latex-bin`, manuels, motifs de césure sans fiche CTAN), collections et schemes.
- `styles` : fichiers `.sty` et `.cls` des runfiles sous `tex/{latex,generic,xelatex,lualatex,xetex,luatex}/`,
  les arbres propres à LaTeX et à ses moteurs. Le `TEXINPUTS` de pdfLaTeX, XeLaTeX et LuaLaTeX finit
  par `tex//` : les fichiers de `tex/platex`, `tex/latex-dev`, `tex/plain`… restent accessibles, mais
  ne sont volontairement pas indexés (formats non proposés, doublons de pré-version).
  `byStyle` en est l'index inverse (fichier → packages, liste triée).
- `ctanUrl` prend l'identifiant du catalogue CTAN quand il diffère du nom TeX Live
  (`amsmath` → `latex-amsmath`), et vaut `null` quand le paquet n'a pas de fiche au catalogue (aucun
  champ `catalogue*` dans la base : `latexconfig`, `xetexconfig`…), plutôt qu'une page CTAN
  inexistante ; `docUrl` pointe vers texdoc.org.
- `collection` : collection TeX Live qui dépend du package. `shortdesc`, `license`, `version`,
  `ctanUrl` et `collection` valent `null` quand la base ne les donne pas ; `license` garde la valeur
  brute (plusieurs licences séparées par une espace).
- Taille pour TeX Live 2026 complet : environ 4 820 packages, 7 600 fichiers de style, 1,9 Mo
  (310 ko en gzip).

Publication : la CI extrait le JSON de chaque image (`docker create` + `docker cp`) et l'attache comme
artefact `package-index-<variante>`. Sur `main`, une fois le lint (dont les tests unitaires du
générateur) et les deux variantes réussis, le job `publish package index (R2)` le copie dans
Cloudflare R2 (`aws s3 cp --endpoint-url`, `Cache-Control: public, max-age=3600`) :

| Clé                                        | Contenu                                                            |
| ------------------------------------------ | ------------------------------------------------------------------ |
| `texlive/<année>/packages.json`            | index de référence, lu par l'API : image `full`, tous les packages |
| `texlive/<année>/<variante>/packages.json` | index de chaque variante (`medium`, `full`)                        |

Configuration du dépôt GitHub (Settings → Environments), dans cet ordre :

1. Ouvrir ou créer l'environnement `r2-package-index`. Il peut déjà exister : GitHub crée
   automatiquement, **sans aucune règle**, un environnement référencé par un job, donc dès le premier
   run sur `main` (push ou reconstruction hebdomadaire). Un environnement présent n'est pas pour autant
   protégé.
2. Vérifier ou poser la règle « Deployment branches and tags » = « Selected branches and tags »,
   avec la seule règle de branche `main`, **avant** d'ajouter les secrets.
3. Y définir les secrets `R2_ACCESS_KEY_ID` et `R2_SECRET_ACCESS_KEY` (jeton R2 « Object Read &
   Write » limité à ce bucket) et les variables `R2_ENDPOINT`
   (`https://<compte>.r2.cloudflarestorage.com`) et `R2_PUBLIC_BUCKET`.

Ces secrets ne doivent pas exister au niveau du dépôt : tout workflow de n'importe quelle branche
pourrait les lire, alors que seul un job de `main` reçoit ceux de l'environnement. Le job commence par
lire la règle de l'environnement (API GitHub, permission `actions: read`, seule permission du job) et
échoue si elle n'est pas exactement « branche `main` » : une configuration créée automatiquement est
ainsi signalée dès le premier run sur `main`. Ce contrôle ne remplace pas la règle, qu'une branche
modifiant le workflow contournerait. La règle en place, sans secrets ni variables R2, la publication
est sautée avec un avis dans le run.

## CI

`.github/workflows/build.yml` :

- lint : shellcheck, hadolint, gitleaks, tests unitaires de l'index des packages ;
- build des deux variantes, chacune sur sa propre architecture : `medium` en amd64, `full` en arm64 sur un runner ARM natif ;
- index des packages extrait de chaque image et attaché comme artefact ;
- tests de fumée et suite malveillante, sous runc puis sous gVisor ;
- sur `main`, publication sur GHCR, puis sur ECR si la variable `AWS_ECR_PUSH_ROLE_ARN` est définie (rôle OIDC créé par `kaxolax-infra`, avec la variable `AWS_REGION`) ;
- sur `main`, une fois le lint et les deux variantes réussis, publication de l'index des packages dans R2 depuis l'environnement `r2-package-index`, après contrôle de sa règle de déploiement (voir « Index des packages »).

Une reconstruction hebdomadaire récupère les correctifs de sécurité Debian.
