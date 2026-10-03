#!/usr/bin/env bash
# Installe TeX Live avec install-tl dans /usr/local/texlive/$TEXLIVE_YEAR.
#
# Variables :
#   TEXLIVE_YEAR        année de TeX Live (ex. 2026), obligatoire
#   TEXLIVE_SCHEME      medium (dev et production) ou full, obligatoire
#   TEXLIVE_REPOSITORY  dépôt tlnet à utiliser (facultatif) ; par défaut, l'archive historique figée
#                       si l'année est terminée, sinon le dépôt courant via mirror.ctan.org
set -euo pipefail

: "${TEXLIVE_YEAR:?TEXLIVE_YEAR is required}"
: "${TEXLIVE_SCHEME:?TEXLIVE_SCHEME is required}"

case "$TEXLIVE_SCHEME" in
  medium | full) ;;
  *)
    echo "TEXLIVE_SCHEME must be medium or full, got: $TEXLIVE_SCHEME" >&2
    exit 1
    ;;
esac

historic="https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/${TEXLIVE_YEAR}/tlnet-final"
repository="${TEXLIVE_REPOSITORY:-}"
if [[ -z "$repository" ]]; then
  if curl -fsSIL --retry 3 -o /dev/null "$historic/tlpkg/texlive.tlpdb"; then
    repository="$historic"
  else
    # Résout la redirection une seule fois : toute l'installation vient du même miroir.
    # mirror.ctan.org choisit un miroir à chaque requête, et certains ont un certificat incomplet
    # ou sont indisponibles : on retient le premier qui sert texlive.tlpdb avec un TLS vérifié.
    for attempt in 1 2 3 4 5 6 7 8; do
      if resolved=$(curl -fsSIL --retry 2 -o /dev/null -w '%{url_effective}' \
        https://mirror.ctan.org/systems/texlive/tlnet/tlpkg/texlive.tlpdb); then
        repository="${resolved%/tlpkg/texlive.tlpdb}"
        break
      fi
      echo "CTAN mirror attempt ${attempt} failed, asking for another mirror" >&2
      sleep 5
    done
    if [[ -z "$repository" ]]; then
      echo "No CTAN mirror served TeX Live over verified TLS" >&2
      exit 1
    fi
  fi
fi
echo "TeX Live ${TEXLIVE_YEAR} (${TEXLIVE_SCHEME}) from ${repository}"

workdir=$(mktemp -d)
curl -fsSL --retry 5 "$repository/install-tl-unx.tar.gz" | tar -xz -C "$workdir" --strip-components=1

# L'installeur doit correspondre à l'année demandée (le dépôt courant avance d'année en mars).
installer_year=$(sed -n 's/.*version \([0-9]\{4\}\).*/\1/p' "$workdir/release-texlive.txt" | head -1)
if [[ "$installer_year" != "$TEXLIVE_YEAR" ]]; then
  echo "Repository provides TeX Live ${installer_year}, not ${TEXLIVE_YEAR}" >&2
  exit 1
fi

texdir="/usr/local/texlive/${TEXLIVE_YEAR}"
cat >"$workdir/texlive.profile" <<PROFILE
selected_scheme scheme-${TEXLIVE_SCHEME}
TEXDIR ${texdir}
TEXMFLOCAL /usr/local/texlive/texmf-local
TEXMFSYSCONFIG ${texdir}/texmf-config
TEXMFSYSVAR ${texdir}/texmf-var
TEXMFHOME ~/texmf
TEXMFVAR ~/.texlive${TEXLIVE_YEAR}/texmf-var
TEXMFCONFIG ~/.texlive${TEXLIVE_YEAR}/texmf-config
instopt_adjustpath 0
instopt_adjustrepo 0
instopt_letter 0
instopt_portable 0
instopt_write18_restricted 0
tlpdbopt_autobackup 0
tlpdbopt_install_docfiles 0
tlpdbopt_install_srcfiles 0
tlpdbopt_create_formats 1
tlpdbopt_post_code 1
PROFILE

# install-tl vérifie la signature GPG du dépôt (gpg est installé dans l'étape de build).
"$workdir/install-tl" --profile "$workdir/texlive.profile" --repository "$repository" --no-interaction \
  2>&1 | tee "$workdir/install.log"

bindir="${texdir}/bin/$(uname -m)-linux"
tlmgr="${bindir}/tlmgr"

# install-tl continue quand un miroir ne sert pas un paquet (« inessential packages failed ») :
# l'image serait incomplète sans que le build échoue. On relance ces paquets, puis on vérifie.
failed=$(awk '/packages failed to install properly:/ { listing = 1; next }
              /You can fix this/ { listing = 0 }
              listing { print }' "$workdir/install.log" | xargs)
if [[ -n "$failed" ]]; then
  echo "Packages that failed to install, retrying: $failed"
  for attempt in 1 2 3; do
    # shellcheck disable=SC2086 # une liste de noms de paquets
    if "$tlmgr" update --all --reinstall-forcibly-removed &&
      "$tlmgr" info --only-installed --data name $failed >/dev/null; then
      break
    fi
    if [[ "$attempt" == 3 ]]; then
      echo "Packages still missing after 3 attempts: $failed" >&2
      exit 1
    fi
    sleep $((attempt * 15))
  done
fi

# Le schéma medium n'inclut ni biber ni latexextra : on ajoute ce qu'un projet courant attend.
if [[ "$TEXLIVE_SCHEME" == medium ]]; then
  "$tlmgr" install collection-latexextra collection-bibtexextra collection-fontsrecommended
fi
"$tlmgr" install latexmk biber synctex

# Formats qu'install-tl n'a pas construits (paquet absent à ce moment-là), construits maintenant
# que tous les paquets sont là, puis base ls-R à jour : kpathsea ne cherche les formats de
# TEXMFSYSVAR que dans ls-R. Un format introuvable serait reconstruit dans chaque conteneur neuf,
# à chaque compilation (≈ 10 s pour XeLaTeX).
"${bindir}/fmtutil-sys" --no-error-if-no-engine=luametatex,luajithbtex,luajittex,mfluajit --missing
"${bindir}/mktexlsr" "${texdir}/texmf-var"
for format in pdftex:pdflatex xetex:xelatex luahbtex:lualatex; do
  if ! "${bindir}/kpsewhich" -engine="${format%%:*}" "${format#*:}.fmt"; then
    echo "Format ${format#*:} (${format%%:*}) is missing" >&2
    grep -n "web2c/${format%%:*}" -A3 "${texdir}/texmf-var/ls-R" >&2 || true
    ls -la "${texdir}/texmf-var/web2c/${format%%:*}" >&2 || true
    exit 1
  fi
done

# Chemins indépendants de l'année et de l'architecture (x86_64-linux ou aarch64-linux).
ln -s "$bindir" /usr/local/texlive/bin
ln -s "${texdir}/texmf-dist/fonts" /usr/local/texlive/texmf-dist-fonts

rm -rf "$workdir" "${texdir}/tlpkg/backups" "${texdir}/install-tl.log" "${texdir}/texmf-var/web2c/"*.log
