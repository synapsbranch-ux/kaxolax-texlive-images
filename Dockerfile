# syntax=docker/dockerfile:1

# Image TeX Live du sandbox de compilation Kaxolax.
#   docker build --build-arg TEXLIVE_YEAR=2026 --build-arg TEXLIVE_SCHEME=medium -t kaxolax-texlive:2026-medium .
# Variantes : medium (développement local) et full (staging).

ARG DEBIAN_IMAGE=debian:trixie-20260918-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a

FROM ${DEBIAN_IMAGE} AS installer
ARG TEXLIVE_YEAR=2026
ARG TEXLIVE_SCHEME=medium
ARG TEXLIVE_REPOSITORY=
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gnupg perl xz-utils \
  && rm -rf /var/lib/apt/lists/*
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
COPY texmf.cnf /tmp/kaxolax-texmf.cnf
COPY fontconfig/09-texlive-fonts.conf /etc/fonts/conf.d/09-texlive-fonts.conf
COPY --chmod=0755 bin/biber bin/lualatex /opt/kaxolax/bin/
COPY install/warmup-fonts.tex /usr/share/kaxolax/warmup-fonts.tex
COPY tests/malicious /usr/share/kaxolax/malicious

ENV PATH=/opt/kaxolax/bin:/usr/local/texlive/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/tmp \
  TEXMFVAR=/tmp/texmf-var \
  LANG=C.UTF-8 \
  KAXOLAX_TEXLIVE_YEAR=${TEXLIVE_YEAR} \
  KAXOLAX_TEXLIVE_SCHEME=${TEXLIVE_SCHEME}

# Réglages durcis placés en tête du texmf.cnf local (kpathsea retient la première définition, et
# install-tl y écrit déjà shell_escape), puis caches de polices construits une fois pour
# toutes : à l'exécution, l'image est en lecture seule et seuls /tmp et /tmp/biber sont
# inscriptibles (voir bin/biber et bin/lualatex).
# Chaque moteur doit trouver son format dans l'image (MKTEXFMT=0 : aucune reconstruction), sinon
# chaque compilation, dans un conteneur neuf, le reconstruirait.
# openin_any n'a plus d'effet depuis TeX Live 2026 : TeX et Lua peuvent lire tout fichier de
# l'image. /etc/passwd et /etc/group sont donc illisibles pour l'UID 1000 du sandbox.
RUN cat /tmp/kaxolax-texmf.cnf "/usr/local/texlive/${TEXLIVE_YEAR}/texmf.cnf" > /tmp/texmf.cnf \
  && mv /tmp/texmf.cnf "/usr/local/texlive/${TEXLIVE_YEAR}/texmf.cnf" \
  && rm /tmp/kaxolax-texmf.cnf \
  && fc-cache -f \
  && export TEXMFVAR="/usr/local/texlive/${TEXLIVE_YEAR}/texmf-var" \
  && luaotfload-tool --update --force \
  && /usr/local/texlive/bin/lualatex -interaction=batchmode -output-directory=/tmp \
    /usr/share/kaxolax/warmup-fonts.tex \
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
COPY --from=index /packages.json /usr/share/kaxolax/packages.json

LABEL org.opencontainers.image.title="kaxolax-texlive" \
  org.opencontainers.image.description="TeX Live ${TEXLIVE_YEAR} (${TEXLIVE_SCHEME}) for the Kaxolax compile sandbox" \
  org.opencontainers.image.source="https://github.com/synapsbranch-ux/kaxolax-texlive-images" \
  dev.kaxolax.texlive.year="${TEXLIVE_YEAR}" \
  dev.kaxolax.texlive.scheme="${TEXLIVE_SCHEME}"

USER 1000:1000
WORKDIR /compile
CMD ["latexmk", "-v"]
