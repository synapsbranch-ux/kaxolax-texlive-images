# texink-texlive-images

Images Docker TeX Live utilisées par le sandbox de compilation de **Tex.ink**.

| Variante | Usage                          | Architecture             | Tag                    |
| -------- | ------------------------------ | ------------------------ | ---------------------- |
| `medium` | développement local et production (conteneur de compilation Cloudflare) | amd64 | `texink-texlive:2026-medium` |
| `full`   | toute la distribution, construite pour comparaison                       | amd64 | `texink-texlive:2026-full`   |

Contenu de l'image :

- Debian trixie slim (épinglée par digest) et TeX Live installé par `install-tl`, l'année étant un argument de build.
- `medium` = `scheme-medium` + `collection-latexextra` + `collection-bibtexextra` + `collection-fontsrecommended`.
- pdflatex, xelatex, lualatex, bibtex, biber, latexmk et synctex.
- pandoc 3.12 (binaire statique officiel, empreinte vérifiée) et son filtre Lua contrôlé, pour la conversion Markdown → LaTeX (voir « Conversion Markdown → LaTeX »).
- Polices Noto (dont CJK) et Liberation pour XeLaTeX et LuaLaTeX. Les polices OpenType de TeX Live sont visibles par fontconfig.
- `texmf.cnf` durci (`openin_any = p`, `openout_any = p`, `shell_escape = f`).
- Utilisateur UID 1000, `HOME=/tmp`. Caches de polices (fontconfig, luaotfload) construits au build.
- La suite de tests malveillants est copiée dans `/usr/share/texink/malicious`, pour que l'agent de compilation la rejoue.
- L'index des packages TeX Live de l'image est dans `/usr/share/texink/packages.json` (voir « Index des packages »).

## Prérequis

- Docker (Docker Desktop avec l'intégration WSL2 sous Windows) ;
- Python 3 (tests) ;
- pour tester sous gVisor : `sudo GVISOR_RELEASE=20260928.0 scripts/install-gvisor.sh` (Linux uniquement).

## Construire

```bash
docker build --build-arg TEXLIVE_YEAR=2026 --build-arg TEXLIVE_SCHEME=medium -t texink-texlive:2026-medium .
```

Comptez environ 15 minutes pour `medium` et plus d'une heure pour `full`. `TEXLIVE_REPOSITORY`
permet d'imposer un miroir CTAN précis. Par défaut, l'installeur utilise l'archive historique
figée pour une année terminée, sinon `mirror.ctan.org`.

L'image `medium` est aussi publiée sur GHCR à chaque build de `main` :

```bash
docker pull ghcr.io/synapsbranch-ux/texink-texlive:2026-medium
docker tag ghcr.io/synapsbranch-ux/texink-texlive:2026-medium texink-texlive:2026-medium
```

## Tester

Chaque cas lance un conteneur neuf avec exactement les règles du sandbox de l'agent :

- `--network none`, UID 1000, `--read-only`, `/tmp` en tmpfs `noexec` ;
- `--cap-drop ALL`, `no-new-privileges` ;
- 2 Go de mémoire, 1 CPU, 256 processus ;
- `RLIMIT_FSIZE` à 101 Mo (le plafond du PDF est de 100 Mo) ;
- timeout suivi de `docker kill`.

```bash
python3 tests/run_cases.py --image texink-texlive:2026-medium tests/smoke tests/malicious
python3 tests/run_cases.py --image texink-texlive:2026-medium --runtime runsc tests/malicious   # gVisor
python3 tests/run_cases.py --image texink-texlive:2026-medium --only lua tests/malicious        # filtre
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
| `pandoc-read-files`                         | images `/etc/passwd`, `../../`, fichier de l'hôte, `file://` | `--sandbox`, filtre Tex.ink (texte alternatif à la place) |
| `pandoc-raw-latex`                          | `\input`, `\write18`, bloc `{=latex}`, HTML brut       | extensions `raw_tex`, `raw_attribute`, `raw_html` désactivées |
| `pandoc-raw-latex-allowed`                  | les mêmes avec l'option `rawLatex`                     | recopiés sans être lus ; la compilation reste bloquée par le sandbox |
| `pandoc-math-latex`                         | `\input`, `\write18`, `\directlua` dans `$…$`, `$$…$$` et `header-includes` | recopiés sans échappement (formules) ; la compilation reste bloquée par le sandbox |
| `pandoc-filters`                            | filtre, défauts et modèle du projet (YAML, `templates/`, `defaults/`) | commande constante, `--data-dir` de l'image |
| `pandoc-extract-media`                      | images `data:` (nom `../`, SVG, HTML), image hors projet | seuls PNG, JPEG et PDF extraits, sous `media/<sha1>.<ext>` |
| `pandoc-remote-resources`                   | images et bibliographie distantes (métadonnées du cloud) | `--sandbox`, pas de `--citeproc`, `--network none` ; images changées en liens |
| `pandoc-citation-keys`                      | clés `@{…}` contenant `\input`, `\write18`, `%` (biblatex) | filtre Tex.ink : citation laissée en texte échappé, clé signalée |
| `pandoc-yaml-bomb`                          | bombe YAML (alias imbriqués)                          | tas plafonné (`+RTS -M512m`) et délai                       |

**Attention, TeX Live 2026 :** `openin_any` n'a plus aucun effet. TeX Live l'a supprimé en
décembre 2025 (voir les commentaires de `texmf-dist/web2c/texmf.cnf`). TeX et Lua peuvent donc
lire tout fichier présent dans l'image. La protection en lecture repose sur deux points :

- l'isolation du conteneur : seul le répertoire de travail du projet est monté, et rien de sensible ne se trouve dans l'image ;
- `/etc/passwd` et `/etc/group` sont illisibles pour l'UID 1000.

La valeur `openin_any = p` reste dans `texmf.cnf` : elle est sans effet, mais elle s'appliquerait
à une année antérieure.

## Conversion Markdown → LaTeX (pandoc)

L'agent de compilation (`apps/compile-agent` de texink-platform, opération `convert`) lance pandoc
dans le sandbox de compilation, avec les mêmes règles qu'une compilation (aucun réseau, UID 1000,
racine en lecture seule, limites de mémoire, de processus et de taille de fichier, délai). Le
répertoire de travail ne contient que `input.md`, `texink-convert.json` (options du filtre) et
`media/`. La commande est constante, à des valeurs de listes fermées près (classe, découpage,
`--natbib` ou `--biblatex`) :

```bash
pandoc +RTS -M512m -RTS --sandbox --data-dir=/usr/share/texink/pandoc \
  --lua-filter=/usr/share/texink/pandoc/texink-convert.lua \
  --from=markdown-raw_tex-raw_attribute-raw_html --to=latex --standalone --wrap=preserve \
  --variable=documentclass:article --natbib --output=output.tex input.md
```

- Version : pandoc 3.12, archive officielle des releases GitHub, empreinte SHA-256 vérifiée par
  `ADD --checksum` (amd64 et arm64) ; seul le binaire `pandoc` est installé (`/usr/local/bin`).
- `--sandbox` : les lecteurs et rédacteurs de pandoc ne lisent aucun fichier ni URL (images,
  inclusions). `+RTS -M512m` : tas plafonné (une bombe YAML échoue au lieu d'épuiser la mémoire).
- `--data-dir` : répertoire de l'image (`pandoc/` du dépôt), en lecture seule ; aucun modèle,
  défaut ou filtre ne vient du projet ni du répertoire personnel.
- Filtres : seul `pandoc/texink-convert.lua` s'exécute. `--sandbox` ne couvre pas les filtres Lua,
  d'où un filtre minimal : il ne lit que son fichier d'options, n'appelle
  `pandoc.mediabag.fetch` que sur une URI `data:` (décodée en mémoire) et n'écrit que
  `media/<sha1>.<ext>` et `texink-report.json`. Il réécrit les chemins des images (relatifs au
  fichier Markdown → relatifs au document principal), change les images distantes en liens,
  remplace les chemins absolus ou hors du projet par leur texte alternatif, extrait les images
  `data:` PNG, JPEG et PDF (plafond de fichiers distincts : une image répétée ne compte pas), et
  encadre le corps de deux marqueurs aléatoires (fragment).
- Citations `[@clé]` : commandes natbib ou biblatex (`--natbib`, `--biblatex`), jamais
  `--citeproc`. pandoc recopie les clés telles quelles, même `@{x\input{…}}` : le filtre ne garde
  que les clés de l'alphabet sûr (lettres, chiffres, `_:.-+/`) ; la citation d'une autre clé reste
  du texte échappé et la clé est rapportée (`rejectedCitations`, cas `pandoc-citation-keys`).
- LaTeX brut du texte : échappé par défaut. Avec `rawLatex`, il est recopié tel quel. Dans tous
  les cas, pandoc recopie sans échappement le contenu des formules (`$…$`, `$$…$$`), y compris
  dans les métadonnées YAML (`header-includes`, titre) : `$\input{…}$` ou
  `$$\directlua{…}$$` passent même sans `rawLatex`. Le LaTeX produit n'est donc jamais digne de
  confiance et le sandbox de compilation est la seule barrière (cas `pandoc-math-latex`).
- `--extract-media` n'est pas utilisé : sous `--sandbox`, pandoc n'extrait rien ; le filtre écrit
  lui-même les images intégrées, sous un nom dérivé de leur contenu.

Smoke tests : `tests/smoke/pandoc-markdown` convertit un Markdown riche puis compile le résultat
avec pdfLaTeX ; `pandoc-citations` compile des citations natbib avec BibTeX ;
`pandoc-embedded-limit` vérifie le plafond des images `data:` (une image répétée ne compte pas). Les cas `convert` de `case.json` (voir `tests/run_cases.py`) rejouent la commande de
l'agent.

### Tester l'agent sans reconstruire TeX Live

L'étape `pandoc-overlay` ajoute pandoc, le filtre et la suite malveillante à jour à une image TeX
Live existante (développement local, tests d'intégration de l'agent ; jamais en production) :

```bash
docker build --target pandoc-overlay --build-arg PANDOC_OVERLAY_BASE=texink-texlive:2026-medium \
  -t texink-texlive-pandoc:2026-medium .
python3 tests/run_cases.py --image texink-texlive-pandoc:2026-medium --only pandoc tests/smoke tests/malicious
```

## Index des packages

`scripts/package-index.py` (Python 3, bibliothèque standard seule) lit la base des paquets de
TeX Live (`texlive.tlpdb`) et écrit un index JSON trié et déterministe, sans date. Il sert au
gestionnaire de packages de l'éditeur (recherche, ajout d'un `\usepackage`, correction d'une
erreur « File `xyz.sty' not found »).

Le Dockerfile le génère au build dans une étape `index` jetable, depuis la base de l'installation
(`/usr/local/texlive/<année>/tlpkg/texlive.tlpdb`) : python3 n'entre pas dans l'image finale, qui ne
reçoit que `/usr/share/texink/packages.json`. Le build échoue si l'année de la base diffère de
`TEXLIVE_YEAR`, s'il y a moins de 1 000 packages, ou si `amsmath.sty`, `graphicx.sty`,
`hyperref.sty` ou `scrartcl.cls` (koma-script, de catégorie `TLCore`) manquent.

```bash
python3 scripts/package-index.py /usr/local/texlive/2026/tlpkg/texlive.tlpdb -o packages.json
python3 scripts/package-index.py texlive.tlpdb.xz --pretty    # xz accepté, ou l'entrée standard
docker run --rm texink-texlive:2026-medium cat /usr/share/texink/packages.json > packages.json
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
| `texlive/<année>/packages.json`            | index de référence, lu par l'API : image `medium`, celle de la production |
| `texlive/<année>/<variante>/packages.json` | index de chaque variante (`medium`, `full`)                        |

Configuration du dépôt GitHub (Settings → Environments), dans cet ordre :

1. Ouvrir ou créer l'environnement `r2-package-index`. Il peut déjà exister : GitHub crée
   automatiquement, **sans aucune règle**, un environnement référencé par un job, donc dès le premier
   run sur `main` (push ou reconstruction hebdomadaire). Un environnement présent n'est pas pour autant
   protégé.
2. Vérifier ou poser la règle « Deployment branches and tags » = « Selected branches and tags »,
   avec la seule règle de branche `main`, **avant** d'ajouter les secrets.
3. Y définir les secrets `R2_ACCESS_KEY_ID` et `R2_SECRET_ACCESS_KEY` (jeton R2 « Object Read &
   Write » limité à ce bucket : sortie `texlive_publish` de texink-infra) et les variables
   `R2_ENDPOINT` (`https://<compte>.eu.r2.cloudflarestorage.com` : les buckets sont dans la
   juridiction UE, voir `terraform output r2_s3_endpoint`) et `R2_PUBLIC_BUCKET`
   (`texink-templates` : l'index est publié sous le préfixe `texlive/` du bucket public).

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
- build des deux variantes en linux/amd64 (architecture des conteneurs Cloudflare) ;
- index des packages extrait de chaque image et attaché comme artefact ;
- tests de fumée et suite malveillante, sous runc puis sous gVisor ;
- sur `main`, publication sur GHCR ; l'empreinte (`sha256:…`) de chaque image est écrite dans le résumé du run, pour l'épingler dans texink-platform et texink-templates ;
- sur `main`, une fois le lint et les deux variantes réussis, publication de l'index des packages dans R2 depuis l'environnement `r2-package-index`, après contrôle de sa règle de déploiement (voir « Index des packages »).

Une reconstruction hebdomadaire récupère les correctifs de sécurité Debian.
