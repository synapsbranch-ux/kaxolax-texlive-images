# syntax=docker/dockerfile:1

# Image TeX Live du sandbox de compilation Tex.ink.
#   docker build --build-arg TEXLIVE_YEAR=2026 --build-arg TEXLIVE_SCHEME=medium -t texink-texlive:2026-medium .
# Variantes : medium (développement local et production, conteneur de compilation Cloudflare)
# et full (toute la distribution, construite pour comparaison).

ARG DEBIAN_IMAGE=debian:trixie-20260918-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a
# Architecture de la cible (fournie par BuildKit) : choisit l'archive de pandoc.
ARG TARGETARCH
# Image complétée par l'étape `pandoc-overlay` (développement local, voir le README).
ARG PANDOC_OVERLAY_BASE=texink-texlive:2026-medium
ARG PANDOC_VERSION=3.12

# pandoc (conversion Markdown → LaTeX, lancée dans le sandbox de compilation) : binaire statique
# officiel des releases GitHub, version exacte et empreinte de l'archive vérifiée par ADD. La release
# ne publie pas d'empreintes : celles-ci ont été calculées au téléchargement et recoupées avec le
# paquet .deb de la même release (voir docs/decisions.md).
FROM ${DEBIAN_IMAGE} AS pandoc-download-amd64
ARG PANDOC_VERSION
ADD --checksum=sha256:67d7d011fed8c8543306022b985b9b2499ab9b74818df91d8727c7e9ebc5ba06 \
  https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz /tmp/pandoc.tar.gz

FROM ${DEBIAN_IMAGE} AS pandoc-download-arm64
ARG PANDOC_VERSION
ADD --checksum=sha256:6cefcf7100e23a99447c26f89d1ff5b253f3407fcef99a9e27ae06f3ed16cb82 \
  https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-arm64.tar.gz /tmp/pandoc.tar.gz

# Arborescence /out copiée telle quelle dans l'image : le binaire seul (ni pandoc-server ni
# pandoc-lua) et le répertoire de données de Tex.ink (filtre Lua contrôlé, aucun modèle).
# hadolint ignore=DL3006
FROM pandoc-download-${TARGETARCH} AS pandoc
ARG PANDOC_VERSION
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY pandoc /out/usr/share/texink/pandoc
RUN tar -xzf /tmp/pandoc.tar.gz -C /tmp \
  && install -D -m 0755 "/tmp/pandoc-${PANDOC_VERSION}/bin/pandoc" /out/usr/local/bin/pandoc \
  && /out/usr/local/bin/pandoc --version | head -n 1 | grep -qx "pandoc ${PANDOC_VERSION}" \
  && chmod -R a+rX,go-w /out/usr/share/texink/pandoc \
  && rm -rf /tmp/pandoc.tar.gz "/tmp/pandoc-${PANDOC_VERSION}"

# Ajoute pandoc (et la suite malveillante à jour) à une image TeX Live déjà construite, sans
# reconstruire TeX Live : développement local et tests d'intégration de l'agent uniquement.
#   docker build --target pandoc-overlay --build-arg PANDOC_OVERLAY_BASE=<image> -t <tag> .
# hadolint ignore=DL3006
FROM ${PANDOC_OVERLAY_BASE} AS pandoc-overlay
USER root
COPY --from=pandoc /out/ /
COPY tests/malicious /usr/share/texink/malicious
# Règle de l'étape runtime réappliquée : une image de base locale peut ne pas l'avoir.
RUN chmod 0600 /etc/passwd /etc/group
USER 1000:1000

FROM ${DEBIAN_IMAGE} AS installer
ARG TEXLIVE_YEAR=2026
ARG TEXLIVE_SCHEME=medium
ARG TEXLIVE_REPOSITORY=
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gnupg libfontconfig1 perl xz-utils \
  && rm -rf /var/lib/apt/lists/*
# libfontconfig1 : xetex en a besoin pour construire son format pendant l'installation.
COPY install/install-texlive.sh /usr/local/sbin/install-texlive.sh
RUN TEXLIVE_YEAR="${TEXLIVE_YEAR}" TEXLIVE_SCHEME="${TEXLIVE_SCHEME}" \
  TEXLIVE_REPOSITORY="${TEXLIVE_REPOSITORY}" /usr/local/sbin/install-texlive.sh

# Index des packages (JSON) généré depuis la base texlive.tlpdb de l'installation, dans une étape
# jetable : python3 n'entre pas dans l'image finale, qui ne reçoit que le JSON. Le build échoue si
# la base est mal lue (trop peu de packages, styles de base absents, année différente) ;
# scrartcl.cls vérifie que les packages de catégorie TLCore (koma-script) sont bien indexés.
FROM ${DEBIAN_IMAGE} AS index
ARG TEXLIVE_YEAR=2026
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 \
  && rm -rf /var/lib/apt/lists/*
COPY --from=installer /usr/local/texlive/${TEXLIVE_YEAR}/tlpkg/texlive.tlpdb /tmp/texlive.tlpdb
COPY scripts/package-index.py /usr/local/bin/package-index.py
RUN python3 /usr/local/bin/package-index.py /tmp/texlive.tlpdb \
  --texlive-year "${TEXLIVE_YEAR}" \
  --min-packages 1000 \
  --require-style amsmath.sty --require-style graphicx.sty --require-style hyperref.sty \
  --require-style scrartcl.cls \
  --output /packages.json

FROM ${DEBIAN_IMAGE} AS runtime
ARG TEXLIVE_YEAR=2026
ARG TEXLIVE_SCHEME=medium

# perl : latexmk et les scripts TeX Live. Polices Noto et Liberation pour XeLaTeX et LuaLaTeX.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    fontconfig \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-core \
    fonts-noto-mono \
    perl \
  && rm -rf /var/lib/apt/lists/*

COPY --from=installer /usr/local/texlive /usr/local/texlive
COPY --from=pandoc /out/ /
COPY texmf.cnf /tmp/texink-texmf.cnf
COPY fontconfig/09-texlive-fonts.conf /etc/fonts/conf.d/09-texlive-fonts.conf
COPY --chmod=0755 bin/biber bin/lualatex /opt/texink/bin/
COPY install/warmup-fonts.tex /usr/share/texink/warmup-fonts.tex
COPY tests/malicious /usr/share/texink/malicious

ENV PATH=/opt/texink/bin:/usr/local/texlive/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/tmp \
  TEXMFVAR=/tmp/texmf-var \
  LANG=C.UTF-8 \
  TEXINK_TEXLIVE_YEAR=${TEXLIVE_YEAR} \
  TEXINK_TEXLIVE_SCHEME=${TEXLIVE_SCHEME}

# Réglages durcis placés en tête du texmf.cnf local (kpathsea retient la première définition, et
# install-tl y écrit déjà shell_escape), puis caches de polices construits une fois pour
# toutes : à l'exécution, l'image est en lecture seule et seuls /tmp et /tmp/biber sont
# inscriptibles (voir bin/biber et bin/lualatex).
# Chaque moteur doit trouver son format dans l'image (MKTEXFMT=0 : aucune reconstruction), sinon
# chaque compilation, dans un conteneur neuf, le reconstruirait.
# openin_any n'a plus d'effet depuis TeX Live 2026 : TeX et Lua peuvent lire tout fichier de
# l'image. /etc/passwd et /etc/group sont donc illisibles pour l'UID 1000 du sandbox.
RUN cat /tmp/texink-texmf.cnf "/usr/local/texlive/${TEXLIVE_YEAR}/texmf.cnf" > /tmp/texmf.cnf \
  && mv /tmp/texmf.cnf "/usr/local/texlive/${TEXLIVE_YEAR}/texmf.cnf" \
  && rm /tmp/texink-texmf.cnf \
  && fc-cache -f \
  && export TEXMFVAR="/usr/local/texlive/${TEXLIVE_YEAR}/texmf-var" \
  && luaotfload-tool --update --force \
  && /usr/local/texlive/bin/lualatex -interaction=batchmode -output-directory=/tmp \
    /usr/share/texink/warmup-fonts.tex \
  && rm -f /tmp/warmup-fonts.* \
  && unset TEXMFVAR \
  && mkdir /tmp/fmtcheck \
  && printf '%s\n' '\documentclass{article}\begin{document}x\end{document}' > /tmp/fmtcheck/check.tex \
  && for engine in pdflatex xelatex lualatex; do \
    TEXMFVAR=/tmp/texmf-var TEXMFOUTPUT=/tmp/fmtcheck MKTEXFMT=0 \
      "/usr/local/texlive/bin/${engine}" -interaction=batchmode \
      -output-directory=/tmp/fmtcheck /tmp/fmtcheck/check.tex >/dev/null \
      || { echo "${engine}: no usable preloaded format in the image" >&2; exit 1; }; \
  done \
  && rm -rf /tmp/fmtcheck /tmp/texmf-var \
  && useradd --uid 1000 --user-group --home-dir /tmp --no-create-home --shell /usr/sbin/nologin tex \
  && mkdir /compile && chown 1000:1000 /compile \
  && install -d -o 1000 -g 1000 /var/cache/biber \
  && PAR_GLOBAL_TEMP=/var/cache/biber/cache setpriv --reuid=1000 --regid=1000 --clear-groups \
    /usr/local/texlive/bin/biber --version \
  && chmod 0600 /etc/passwd /etc/group

# Copié après les caches de polices : une modification du script d'index ne les reconstruit pas.
COPY --from=index /packages.json /usr/share/texink/packages.json

LABEL org.opencontainers.image.title="texink-texlive" \
  org.opencontainers.image.description="TeX Live ${TEXLIVE_YEAR} (${TEXLIVE_SCHEME}) for the Tex.ink compile sandbox" \
  org.opencontainers.image.source="https://github.com/synapsbranch-ux/texink-texlive-images" \
  dev.texink.texlive.year="${TEXLIVE_YEAR}" \
  dev.texink.texlive.scheme="${TEXLIVE_SCHEME}"

USER 1000:1000
WORKDIR /compile
CMD ["latexmk", "-v"]
