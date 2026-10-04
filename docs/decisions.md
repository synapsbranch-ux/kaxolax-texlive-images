# Décisions

Chaque décision non triviale : contexte, décision, alternatives écartées (cinq lignes au maximum).

## 2026-09-30 · `openin_any` n'a plus d'effet : `/etc/passwd` illisible pour l'UID 1000

- Contexte : depuis TeX Live 2026, `kpse_in_name_ok` renvoie toujours vrai. `\input{/etc/passwd}` et `io.open` lisent n'importe quel fichier de l'image.
- Décision : la lecture est protégée par l'isolation du conteneur (seul le répertoire du projet est monté). En plus, `/etc/passwd` et `/etc/group` sont en `0600` root, et des cas de test vérifient qu'aucun fichier de l'hôte n'est lisible.
- Écartées : rester sur TeX Live 2025 (retard de versions, et les développeurs jugent la protection contournable), ou patcher kpathsea.

## 2026-09-30 · `latexmk -norc`

- Contexte : latexmk exécute, sans aucune restriction TeX, tout `latexmkrc` ou `.latexmkrc` (du Perl) trouvé dans le projet. C'est vérifié par le cas `latexmkrc-perl`.
- Décision : la commande de compilation ajoute `-norc` à celle de la spécification. Aucune configuration latexmk ne vient du projet.

## 2026-09-30 · biber et luaotfload avec une racine en lecture seule

- biber est un exécutable PAR : il s'extrait (~5 s) dans un répertoire inscriptible et exécutable. Le cache extrait au build est recopié par `bin/biber` dans le tmpfs `/tmp/biber` (monté `exec` par l'agent), en environ 1 s. `/tmp` reste `noexec`.
- luaotfload ne lit sa base de noms que dans son cache inscriptible. `bin/lualatex` y recopie la base construite au build. Le cache des polices courantes est pré-chauffé au build (lu en lecture seule) : LuaLaTeX passe de ~4,5 s à ~1,5 s.

## 2026-09-30 · Plafond de sortie par `RLIMIT_FSIZE`

- `--ulimit fsize` vaut 101 Mo, juste au-dessus du plafond de 100 Mo du PDF. Un fichier tronqué par le noyau dépasse donc forcément le plafond, et la compilation passe en `error`.

## 2026-09-30 · Paquets Debian non épinglés, image de base épinglée par digest

- Une version apt épinglée disparaît de l'archive à la mise à jour de sécurité suivante et casse le build. L'image de base est épinglée par digest, et la reconstruction hebdomadaire récupère les correctifs (hadolint DL3008 ignoré).
- Écartée : snapshot.debian.org à date fixe, entièrement reproductible mais sans correctifs de sécurité.

## 2026-09-30 · Publication GHCR en plus d'ECR

- La spécification prévoit ECR. L'image `medium` est aussi publiée sur GHCR (repo public, `GITHUB_TOKEN`, sans secret) : un développeur la récupère sans identifiants AWS et sans 15 minutes de build.
- `medium` est construite en amd64 et `full` en arm64 (runner ARM natif, sans émulation QEMU), chacune testée sous runc et sous gVisor.

## 2026-09-30 · Paquets non installés par un miroir défaillant

- Contexte : lors du build full arm64, un miroir CTAN n'a pas servi une dizaine de paquets (`xits`, `zhnumber`…) ; install-tl les déclare « inessential » et termine sans erreur, et `fmtutil-sys --all` échoue sans bloquer.
- Décision : le script relit la liste des paquets en échec, relance `tlmgr update --all --reinstall-forcibly-removed` (3 tentatives), vérifie qu'ils sont installés puis reconstruit les formats. Le build échoue s'il en manque encore.
- Écarté : épingler un miroir unique (aucun n'est garanti disponible).
- Choix du miroir : `mirror.ctan.org` redirige vers un miroir différent à chaque requête ; le script en demande un autre (8 essais) tant que le TLS ne se vérifie pas ou que `texlive.tlpdb` manque.

## 2026-09-30 · Formats vérifiés dans l'image

- Contexte : en CI, le premier `xelatex` de chaque conteneur prenait ~10 s, car `mktexfmt` reconstruisait `xelatex.fmt` dans `/tmp` (le second : 0,2 s). Chaque compilation tourne dans un conteneur neuf : ce serait 10 s de plus à chaque fois.
- Décision : après tous les `tlmgr install`, `fmtutil-sys --missing` puis `mktexlsr` (kpathsea ne cherche les formats système que dans `ls-R`), et le build échoue si pdfLaTeX, XeLaTeX ou LuaLaTeX ne trouve pas son format avec `MKTEXFMT=0`.

## 2026-10-01 · Index des packages généré depuis `texlive.tlpdb` au build, publié dans R2

- Contexte : le gestionnaire de packages (tâche 10) a besoin de tous les packages de TeX Live et du package qui fournit chaque `.sty`/`.cls` (erreur « File `xyz.sty' not found »).
- Décision : `scripts/package-index.py` (stdlib) lit la base installée dans une étape Docker `index` jetable ; seul `/usr/share/texink/packages.json` entre dans l'image, sans python3. Le build échoue si l'année diffère, s'il y a moins de 1 000 packages ou si des styles de base manquent.
- Périmètre : catégories `Package` et `ConTeXt`, plus les `TLCore` qui ont une fiche au catalogue CTAN ou un `.sty`/`.cls` (TeX Live y range koma-script, dvips, asymptote) ; `ctanUrl` vaut `null` sans fiche. Styles : runfiles `.sty`/`.cls` sous `tex/{latex,generic,xelatex,lualatex,xetex,luatex}` ; `tex/platex`, `tex/latex-dev`, `tex/plain`… restent lisibles (`TEXINPUTS` finit par `tex//`) mais ne sont pas indexés. TeX Live 2026 complet : 4 821 packages, 1,9 Mo.
- Publication : un job séparé (après le lint et les deux images, permission `actions: read` seule) dans l'environnement GitHub `r2-package-index` (déploiement limité à `main`, seul détenteur des secrets R2, absents du dépôt : une autre branche ne peut pas les lire en modifiant le workflow) publie l'index de l'image `full` sous `texlive/<année>/packages.json`, et chaque variante sous `texlive/<année>/<variante>/`. GitHub crée l'environnement sans règle au premier run : le job échoue tant que la règle n'est pas exactement `main`.
- Écartés : le catalogue CTAN interrogé à l'exécution (réseau, ne reflète pas l'image), `tlmgr info --json` (Perl dans l'étape, sortie bien plus lourde).

## 2026-10-03 · pandoc dans l'image, binaire officiel épinglé par empreinte

- Contexte : la conversion Markdown → LaTeX (étape 3, tâche 5) tourne dans le sandbox de compilation, jamais dans l'API. Le pandoc de Debian trixie (3.1.11) est ancien et une version apt épinglée disparaît de l'archive.
- Décision : pandoc 3.12, archive statique officielle des releases GitHub, `ADD --checksum` (amd64 et arm64). La release ne publie pas d'empreintes : elles ont été calculées au téléchargement et recoupées avec le binaire du `.deb` de la même release (même SHA-256). Seul `pandoc` est installé, pas `pandoc-server`.
- Écartés : paquet Debian (version ancienne, non épinglable), image `pandoc/core` (Alpine, autre base).

## 2026-10-03 · Conversion pandoc : `--sandbox`, filtre Lua unique et contrôlé

- `--sandbox` empêche pandoc de lire fichiers et URL, mais ne couvre ni les filtres Lua ni `--extract-media` (qui, sous sandbox, n'extrait plus rien). Un seul filtre, `pandoc/texink-convert.lua` de l'image : il ne décode que des URI `data:`, n'écrit que `media/<sha1>.<ext>` et `texink-report.json`, et réécrit les chemins d'images.
- Commande constante (`--data-dir` de l'image, aucun modèle, défaut ni filtre du projet), tas plafonné `+RTS -M512m`, mêmes règles de conteneur qu'une compilation. LaTeX brut du texte échappé par défaut ; autorisé, il reste compilé dans le sandbox. Le contenu des formules (métadonnées YAML comprises) est toujours recopié tel quel : le sandbox de compilation est la seule barrière (cas `pandoc-math-latex`).
- Cas malveillants `pandoc-*` (lecture de fichiers, LaTeX brut, filtres et modèles du projet, images `data:`, ressources distantes, bombe YAML) et smoke test compilé.

## 2026-10-03 · Étape `pandoc-overlay`

- Contexte : reconstruire TeX Live (15 min, miroirs CTAN et Debian) pour tester l'agent avec pandoc est inutilement coûteux.
- Décision : l'étape `--target pandoc-overlay` ajoute à une image existante le même `/out` (binaire et filtre), la suite malveillante à jour et `chmod 0600 /etc/passwd /etc/group`. Développement et tests seulement : l'image publiée reste l'étape `runtime`.

## 2026-10-03 · Filtre pandoc : citations et plafond des images intégrées

- Les citations `[@clé]` sont rendues par natbib ou biblatex (`--natbib`/`--biblatex`, liste fermée de l'agent) ; `--citeproc` reste exclu (pas de lecture de bibliographie ni de réseau pendant la conversion).
- pandoc écrit les clés telles quelles dans `\citep{…}`/`\autocite{…}`, y compris la syntaxe `@{…}` qui accepte du LaTeX : le filtre refuse toute clé hors de l'alphabet sûr (lettres, chiffres, `_:.-+/`), la citation reste du texte échappé et la clé est rapportée (`rejectedCitations`).
- Plafond des images `data:` : il porte sur les fichiers écrits ; une image répétée (même SHA-1, déjà dans `media/`) est décodée puis réutilisée sans compter, au lieu d'être remplacée par son texte une fois le plafond atteint.
