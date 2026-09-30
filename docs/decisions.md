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
