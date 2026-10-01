#!/usr/bin/env python3
"""Génère l'index JSON des packages TeX Live à partir de la base texlive.tlpdb.

    python3 scripts/package-index.py /usr/local/texlive/2026/tlpkg/texlive.tlpdb -o packages.json
    python3 scripts/package-index.py texlive.tlpdb.xz --pretty
    xz -dc texlive.tlpdb.xz | python3 scripts/package-index.py > packages.json

Bibliothèque standard uniquement : le script tourne dans une étape jetable du Dockerfile, et seul
le JSON est copié dans l'image finale (/usr/share/kaxolax/packages.json).

Format de texlive.tlpdb : un enregistrement par paquet, séparés par une ligne vide ; une ligne
« clé valeur » par attribut ; les listes de fichiers (runfiles, docfiles, srcfiles, binfiles)
suivent leur clé, une ligne par fichier, commençant par une espace.

Paquets indexés : catégories Package et ConTeXt, et paquets TLCore qui ont une fiche au catalogue
CTAN ou fournissent un .sty/.cls (koma-script, dvips, xetex…). Exclus : paquets d'architecture,
collections, schemes, 00texlive.* et le reste de TLCore (texlive.infra, latex-bin, manuels…).

Sortie (triée et déterministe, sans date) :
    {"texliveYear": 2026, "generatedFrom": "texlive.tlpdb",
     "packages": [{"name", "shortdesc", "category", "topics", "license", "version", "ctanUrl",
                   "docUrl", "styles", "collection"}, ...],
     "byStyle": {"graphicx.sty": ["graphics"], ...}}
"""

from __future__ import annotations

import argparse
import json
import lzma
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

XZ_MAGIC = b"\xfd7zXZ\x00"
GENERATED_FROM = "texlive.tlpdb"
# Catégories toujours indexées ; collections et schemes servent seulement à remplir `collection`.
KEPT_CATEGORIES = frozenset({"Package", "ConTeXt"})
# TLCore mêle l'infrastructure de TeX Live (texlive.infra, latex-bin, manuels, motifs de césure) et
# de vrais packages (koma-script, dvips, asymptote, xetex…) : seuls ces derniers sont indexés, voir
# is_indexed(). La catégorie TLCore est conservée telle quelle dans la sortie.
CORE_CATEGORY = "TLCore"
COLLECTION_CATEGORY = "Collection"
# Enregistrements de configuration de la base (00texlive.config, 00texlive.installation…).
INTERNAL_PREFIX = "00texlive."
FILE_SECTIONS = frozenset({"runfiles", "docfiles", "srcfiles", "binfiles"})
# Préfixe d'arbre des chemins : texmf-dist/ dans la base installée, RELOC/ dans celle du dépôt.
TREE_PREFIXES = frozenset({"RELOC", "texmf-dist", "texmf"})
# Arbres tex/<x>/ propres à LaTeX et à ses moteurs pdfLaTeX, XeLaTeX et LuaLaTeX. Le TEXINPUTS de
# ces formats finit par tex// : les fichiers de tex/platex, tex/latex-dev, tex/plain… leur restent
# accessibles, mais ne sont volontairement pas indexés (formats que Kaxolax ne propose pas, ou
# doublons de pré-version).
STYLE_TREES = frozenset({"latex", "generic", "xelatex", "lualatex", "xetex", "luatex"})
STYLE_EXTENSIONS = (".sty", ".cls")
# Suffixe des paquets d'architecture : kpathsea.x86_64-linux, tex.windows, biber.universal-darwin…
ARCH_SUFFIX = re.compile(r"[a-z0-9_]+(?:-[a-z0-9_]+)+|windows|win32|win64")
RELEASE_DEPEND = re.compile(r"release/(\d{4})")


class PackageIndexError(Exception):
    """Entrée invalide ou index qui ne passe pas les vérifications demandées."""


@dataclass
class TlpRecord:
    """Un enregistrement de texlive.tlpdb, réduit aux attributs utiles à l'index."""

    name: str
    line: int
    fields: dict[str, list[str]] = field(default_factory=dict)
    runfiles: list[str] = field(default_factory=list)

    def first(self, key: str) -> str | None:
        values = self.fields.get(key)
        return values[0] if values else None

    def all(self, key: str) -> list[str]:
        return self.fields.get(key, [])

    @property
    def category(self) -> str | None:
        return self.first("category")

    @property
    def in_ctan_catalogue(self) -> bool:
        """Vrai si le paquet a une fiche au catalogue CTAN, donc une page ctan.org/pkg/<id>.

        TeX Live recopie les champs `catalogue-*` depuis cette fiche. `catalogue-ctan` (chemin sur
        CTAN) manque pour les paquets développés dans TeX Live (latex, xetex, dvips…), qui ont
        pourtant leur page : n'importe quel champ du catalogue suffit.
        """
        return any(key == "catalogue" or key.startswith("catalogue-") for key in self.fields)


def parse_tlpdb(text: str) -> list[TlpRecord]:
    """Découpe le texte de texlive.tlpdb en enregistrements (ordre du fichier conservé)."""
    records: list[TlpRecord] = []
    name: str | None = None
    name_line = start = 0
    fields: dict[str, list[str]] = {}
    runfiles: list[str] = []
    section: str | None = None

    def close() -> None:
        nonlocal name, fields, runfiles, section
        if name is not None:
            records.append(TlpRecord(name=name, line=name_line, fields=fields, runfiles=runfiles))
        elif fields or runfiles:
            raise PackageIndexError(f"line {start}: record without a name")
        name, fields, runfiles, section = None, {}, [], None

    # split("\n") et non splitlines() : une description peut contenir \f ou U+2028.
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        if not line.strip():
            close()
            start = 0
            continue
        start = start or number
        if line.startswith(" "):
            # Ligne de fichier : seul le chemin compte (des attributs peuvent suivre).
            if section is None:
                raise PackageIndexError(f"line {number}: file entry outside a file list")
            if section == "runfiles":
                runfiles.append(line.split()[0])
            continue
        key, _, value = line.partition(" ")
        value = value.strip()
        if key == "name":
            if name is not None:
                # Enregistrement suivant sans ligne vide de séparation.
                close()
                start = number
            if not value:
                raise PackageIndexError(f"line {number}: empty package name")
            name, name_line = value, number
        else:
            fields.setdefault(key, []).append(value)
        section = key if key in FILE_SECTIONS else None
    close()
    return records


def style_file(path: str) -> str | None:
    """Nom du fichier .sty ou .cls chargeable par LaTeX, ou None pour tout autre fichier."""
    parts = path.split("/")
    if parts and parts[0] in TREE_PREFIXES:
        parts = parts[1:]
    if len(parts) < 3 or parts[0] != "tex" or parts[1] not in STYLE_TREES:
        return None
    filename = parts[-1]
    return filename if filename.endswith(STYLE_EXTENSIONS) else None


def is_arch_package(record: TlpRecord, by_name: dict[str, TlpRecord]) -> bool:
    """Vrai pour un paquet de binaires `<pkg>.<arch>` (même si sa catégorie est Package)."""
    base, dot, suffix = record.name.rpartition(".")
    if not dot or not base:
        return False
    parent = by_name.get(base)
    if parent is not None and f"{base}.ARCH" in parent.all("depend"):
        return True
    return ARCH_SUFFIX.fullmatch(suffix) is not None


def is_indexed(record: TlpRecord, styles: list[str]) -> bool:
    """Vrai pour un package à indexer (les paquets d'architecture sont écartés à part).

    Un paquet TLCore n'est retenu que s'il a une fiche au catalogue CTAN ou fournit un .sty/.cls.
    """
    if record.name.startswith(INTERNAL_PREFIX):
        return False
    if record.category in KEPT_CATEGORIES:
        return True
    return record.category == CORE_CATEGORY and (bool(styles) or record.in_ctan_catalogue)


def release_year(by_name: dict[str, TlpRecord]) -> int | None:
    """Année de TeX Live déclarée par 00texlive.config (`depend release/2026`)."""
    config = by_name.get("00texlive.config")
    if config is None:
        return None
    for depend in config.all("depend"):
        match = RELEASE_DEPEND.fullmatch(depend)
        if match:
            return int(match.group(1))
    return None


def build_index(records: list[TlpRecord], texlive_year: int | None = None) -> dict:
    """Construit l'index : packages triés par nom et index inverse fichier de style → packages.

    `texlive_year` (argument de build) doit concorder avec l'année de la base si elle la donne.
    """
    by_name: dict[str, TlpRecord] = {}
    for record in records:
        if record.name in by_name:
            raise PackageIndexError(
                f"line {record.line}: duplicate package {record.name!r} "
                f"(first defined line {by_name[record.name].line})"
            )
        by_name[record.name] = record

    year = release_year(by_name)
    if texlive_year is not None:
        if year is not None and year != texlive_year:
            raise PackageIndexError(f"tlpdb is TeX Live {year}, expected {texlive_year}")
        year = texlive_year

    collections: dict[str, set[str]] = {}
    for record in records:
        if record.category == COLLECTION_CATEGORY:
            for depend in record.all("depend"):
                collections.setdefault(depend, set()).add(record.name)

    packages = []
    by_style: dict[str, set[str]] = {}
    for record in sorted(records, key=lambda item: item.name):
        if is_arch_package(record, by_name):
            continue
        styles = sorted({name for name in map(style_file, record.runfiles) if name})
        if not is_indexed(record, styles):
            continue
        for style in styles:
            by_style.setdefault(style, set()).add(record.name)
        topics = sorted({topic for line in record.all("catalogue-topics") for topic in line.split()})
        ctan_url = None
        if record.in_ctan_catalogue:
            # Identifiant CTAN quand il diffère du nom TeX Live (ex. tools → latex-tools).
            ctan_id = record.first("catalogue") or record.name
            ctan_url = f"https://ctan.org/pkg/{quote(ctan_id, safe='')}"
        owners = collections.get(record.name)
        packages.append(
            {
                "name": record.name,
                "shortdesc": record.first("shortdesc") or None,
                "category": record.category,
                "topics": topics,
                "license": record.first("catalogue-license") or None,
                "version": record.first("catalogue-version") or None,
                # null sans fiche au catalogue : https://ctan.org/pkg/<nom> serait une page 404.
                "ctanUrl": ctan_url,
                "docUrl": f"https://texdoc.org/pkg/{quote(record.name, safe='')}",
                "styles": styles,
                # Une collection par package dans TeX Live ; la plus petite par ordre si plusieurs.
                "collection": min(owners) if owners else None,
            }
        )

    return {
        "texliveYear": year,
        "generatedFrom": GENERATED_FROM,
        "packages": packages,
        "byStyle": {style: sorted(by_style[style]) for style in sorted(by_style)},
    }


def read_tlpdb(source: str | None) -> str:
    """Lit la base depuis un fichier ou l'entrée standard (`-`), compressée xz ou non."""
    if source is None or source == "-":
        data = sys.stdin.buffer.read()
    else:
        data = Path(source).read_bytes()
    if data.startswith(XZ_MAGIC):
        data = lzma.decompress(data)
    # Les descriptions sont en UTF-8 ; un octet invalide ne doit pas faire échouer le build.
    return data.decode("utf-8", errors="replace")


def serialize(index: dict, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(index, ensure_ascii=False, indent=2) + "\n"
    return json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n"


def check_index(index: dict, min_packages: int, required_styles: list[str]) -> None:
    """Garde-fous du build : une base mal lue doit faire échouer le build, pas publier un index vide."""
    count = len(index["packages"])
    if count < min_packages:
        raise PackageIndexError(f"only {count} packages indexed, expected at least {min_packages}")
    missing = [style for style in required_styles if style not in index["byStyle"]]
    if missing:
        raise PackageIndexError(f"style files missing from the index: {', '.join(missing)}")


def write_output(content: str, output: str | None) -> None:
    if output is None or output == "-":
        sys.stdout.buffer.write(content.encode("utf-8"))
        sys.stdout.flush()
        return
    # Écriture atomique : jamais de fichier partiel.
    target = Path(output)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "tlpdb", nargs="?", help="texlive.tlpdb ou texlive.tlpdb.xz (par défaut : l'entrée standard)"
    )
    parser.add_argument(
        "-o", "--output", metavar="FICHIER", help="fichier de sortie (par défaut : la sortie standard)"
    )
    parser.add_argument(
        "--texlive-year",
        type=int,
        metavar="ANNÉE",
        help="année de TeX Live attendue (comparée à celle de la base)",
    )
    parser.add_argument(
        "--min-packages",
        type=int,
        default=1,
        metavar="N",
        help="échoue en dessous de N packages indexés (par défaut : 1)",
    )
    parser.add_argument(
        "--require-style",
        action="append",
        default=[],
        metavar="FICHIER",
        help="échoue si aucun package ne fournit ce .sty/.cls (option répétable)",
    )
    parser.add_argument("--pretty", action="store_true", help="JSON indenté")
    args = parser.parse_args(argv)

    try:
        index = build_index(parse_tlpdb(read_tlpdb(args.tlpdb)), texlive_year=args.texlive_year)
        check_index(index, args.min_packages, args.require_style)
        write_output(serialize(index, pretty=args.pretty), args.output)
    except (OSError, lzma.LZMAError, PackageIndexError) as error:
        print(f"package-index: error: {error}", file=sys.stderr)
        return 1
    print(
        f"package-index: {len(index['packages'])} packages, {len(index['byStyle'])} style files"
        f" (TeX Live {index['texliveYear'] or 'unknown'})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
