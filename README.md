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

## CI

`.github/workflows/build.yml` :

- lint : shellcheck, hadolint, gitleaks ;
- build des deux variantes, chacune sur sa propre architecture : `medium` en amd64, `full` en arm64 sur un runner ARM natif ;
- tests de fumée et suite malveillante, sous runc puis sous gVisor ;
- sur `main`, publication sur GHCR, puis sur ECR si la variable `AWS_ECR_PUSH_ROLE_ARN` est définie (rôle OIDC créé par `kaxolax-infra`, avec la variable `AWS_REGION`).

Une reconstruction hebdomadaire récupère les correctifs de sécurité Debian.
