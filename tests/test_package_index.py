"""Tests de scripts/package-index.py (index des packages TeX Live), sans Docker ni TeX Live.

    python3 -m unittest discover -s tests -p 'test_*.py'

La fixture tests/fixtures/texlive.tlpdb reproduit le format de la base installée
(/usr/local/texlive/<année>/tlpkg/texlive.tlpdb) : paquets, paquets TLCore (koma-script, dvips,
infrastructure), collections, scheme, paquets d'architecture et enregistrements de configuration.
"""

from __future__ import annotations

import importlib.util
import json
import lzma
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SCRIPT = TESTS.parent / "scripts" / "package-index.py"
FIXTURE = TESTS / "fixtures" / "texlive.tlpdb"


def load_script():
    # Nom de fichier avec tiret : chargé par chemin. Enregistré dans sys.modules pour dataclasses.
    spec = importlib.util.spec_from_file_location("package_index", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


package_index = load_script()


def run_cli(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        check=False,
        timeout=60,
    )


def index_of(text: str, **kwargs) -> dict:
    return package_index.build_index(package_index.parse_tlpdb(text), **kwargs)


class FixtureIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FIXTURE.read_text(encoding="utf-8")
        cls.index = index_of(cls.text)
        cls.packages = {package["name"]: package for package in cls.index["packages"]}

    def test_header(self):
        self.assertEqual(self.index["texliveYear"], 2026)
        self.assertEqual(self.index["generatedFrom"], "texlive.tlpdb")
        self.assertEqual(list(self.index), ["texliveYear", "generatedFrom", "packages", "byStyle"])

    def test_keeps_only_real_packages(self):
        self.assertEqual(
            [package["name"] for package in self.index["packages"]],
            [
                "amsmath", "babel", "beamer", "biblatex", "booktabs", "context-vim", "dvips",
                "fontspec", "geometry", "graphics", "hyperref", "jsclasses", "koma-script",
                "kpathsea", "latexconfig", "latexmk", "luamplib", "multirow", "pgf", "siunitx",
                "tools",
            ],
        )
        # Exclus : configuration, TLCore sans fiche CTAN ni style, collections, scheme, paquets
        # d'architecture (même de catégorie Package).
        for excluded in (
            "00texlive.config", "00texlive.installation", "texlive.infra", "latex-bin",
            "hyphen-french", "kpathsea.x86_64-linux", "dvips.x86_64-linux",
            "latexmk.x86_64-linux", "texlive.infra.x86_64-linux", "collection-latex",
            "scheme-medium",
        ):
            self.assertNotIn(excluded, self.packages)
        self.assertEqual(self.packages["context-vim"]["category"], "ConTeXt")
        self.assertEqual(self.packages["latexmk"]["category"], "Package")

    def test_tlcore_packages(self):
        # TeX Live classe koma-script en TLCore : il est indexé avec sa catégorie d'origine.
        self.assertEqual(
            self.packages["koma-script"],
            {
                "name": "koma-script",
                "shortdesc": "A bundle of versatile classes and packages",
                "category": "TLCore",
                "topics": [
                    "addr-list", "book-pub", "class", "date-time", "float", "geometry", "io-mgmt",
                    "keyval", "legal", "letter", "notes", "package-mgmt", "page-hf", "toc-etc",
                ],
                "license": "lppl1.3c",
                "version": "3.49.2",
                "ctanUrl": "https://ctan.org/pkg/koma-script",
                "docUrl": "https://texdoc.org/pkg/koma-script",
                # Ni .lco ni .clo, ni la classe de la documentation (sous source/, pas sous tex/).
                "styles": [
                    "scrartcl.cls", "scrbase.sty", "scrbook.cls", "scrlayer-scrpage.sty",
                    "scrlayer.sty", "scrlttr2.cls", "scrreprt.cls", "tocbasic.sty", "typearea.sty",
                ],
                "collection": "collection-latexrecommended",
            },
        )
        by_style = self.index["byStyle"]
        for style in ("scrartcl.cls", "scrreprt.cls", "scrbook.cls", "typearea.sty",
                      "scrlayer-scrpage.sty"):
            self.assertEqual(by_style[style], ["koma-script"], style)
        self.assertNotIn("scrguide.cls", by_style)
        # dvips : styles sous tex/generic, fiche CTAN sans catalogue-ctan (développé dans TeX Live).
        dvips = self.packages["dvips"]
        self.assertEqual(dvips["category"], "TLCore")
        self.assertEqual(dvips["styles"], ["blackdvi.sty", "colordvi.sty", "rotate.sty"])
        self.assertEqual(dvips["ctanUrl"], "https://ctan.org/pkg/dvips")
        self.assertEqual(dvips["license"], "other-free")
        self.assertEqual(by_style["rotate.sty"], ["dvips"])
        # kpathsea : aucun style, mais une fiche au catalogue CTAN.
        self.assertEqual(self.packages["kpathsea"]["styles"], [])
        self.assertEqual(self.packages["kpathsea"]["ctanUrl"], "https://ctan.org/pkg/kpathsea")

    def test_package_fields(self):
        self.assertEqual(
            self.packages["amsmath"],
            {
                "name": "amsmath",
                "shortdesc": "AMS mathematical facilities for LaTeX",
                "category": "Package",
                "topics": ["maths", "tagged-pdf-partially"],
                "license": "lppl1.3c",
                "version": None,
                # `catalogue latex-amsmath` : la page CTAN porte un autre nom que le paquet.
                "ctanUrl": "https://ctan.org/pkg/latex-amsmath",
                "docUrl": "https://texdoc.org/pkg/amsmath",
                "styles": [
                    "amsbsy.sty", "amscd.sty", "amsgen.sty", "amsmath-2018-12-01.sty",
                    "amsmath.sty", "amsopn.sty", "amstex.sty", "amstext.sty", "amsxtra.sty",
                ],
                "collection": "collection-latex",
            },
        )
        pgf = self.packages["pgf"]
        self.assertEqual(pgf["license"], "lppl1.3c gpl2 fdl")
        self.assertEqual(pgf["version"], "3.1.12")
        self.assertEqual(pgf["ctanUrl"], "https://ctan.org/pkg/pgf")
        self.assertEqual(
            pgf["topics"], ["graphics", "graphics-in-tex", "pgf-tikz", "tagged-pdf-partially"]
        )

    def test_ctan_identifier_and_missing_catalogue(self):
        self.assertEqual(self.packages["tools"]["ctanUrl"], "https://ctan.org/pkg/latex-tools")
        self.assertEqual(self.packages["tools"]["docUrl"], "https://texdoc.org/pkg/tools")
        self.assertEqual(self.packages["graphics"]["ctanUrl"], "https://ctan.org/pkg/latex-graphics")
        latexconfig = self.packages["latexconfig"]
        self.assertEqual(latexconfig["shortdesc"], "configuration files for LaTeX-related formats")
        self.assertIsNone(latexconfig["license"])
        self.assertIsNone(latexconfig["version"])
        self.assertEqual(latexconfig["topics"], [])
        self.assertEqual(latexconfig["styles"], [])
        # Aucune fiche au catalogue CTAN : pas de lien vers une page ctan.org inexistante.
        self.assertIsNone(latexconfig["ctanUrl"])
        self.assertEqual(latexconfig["docUrl"], "https://texdoc.org/pkg/latexconfig")

    def test_styles(self):
        self.assertEqual(self.packages["pgf"]["styles"], [
            "pgf.sty", "pgfcore.sty", "pgfkeys.sty", "pgfrcs.sty", "tikz.sty", "xxcolor.sty",
        ])
        self.assertEqual(self.packages["graphics"]["styles"], [
            "color.sty", "epsfig.sty", "graphics-2017-06-25.sty", "graphics.sty", "graphicx.sty",
            "keyval.sty", "lscape.sty", "rotating.sty", "trig.sty",
        ])
        # .cls compris, tri par point de code (majuscules d'abord), fichiers .dict ignorés.
        self.assertEqual(self.packages["beamer"]["styles"], [
            "beamer.cls", "beamerarticle.sty", "beamerbasecolor.sty",
            "beamerbasecompatibility.sty", "beamercolorthemedefault.sty",
            "beamerthemeMadrid.sty", "beamerthemedefault.sty",
        ])
        # Ni .bbx, .cbx, .lbx, .def, .cfg ni .bst.
        self.assertEqual(self.packages["biblatex"]["styles"], ["biblatex.sty"])
        self.assertEqual(
            self.packages["fontspec"]["styles"],
            ["fontspec-luatex.sty", "fontspec-xetex.sty", "fontspec.sty"],
        )
        # tex/generic (babel), tex/luatex (luamplib) ; pas tex/platex ni tex/context.
        self.assertEqual(
            self.packages["babel"]["styles"],
            ["UKenglish.sty", "USenglish.sty", "babel.sty", "french.sty"],
        )
        self.assertEqual(self.packages["luamplib"]["styles"], ["luamplib.sty"])
        self.assertEqual(self.packages["jsclasses"]["styles"], [])
        self.assertEqual(self.packages["context-vim"]["styles"], [])

    def test_by_style(self):
        by_style = self.index["byStyle"]
        self.assertEqual(by_style["graphicx.sty"], ["graphics"])
        self.assertEqual(by_style["tikz.sty"], ["pgf"])
        self.assertEqual(by_style["beamer.cls"], ["beamer"])
        self.assertEqual(list(by_style), sorted(by_style))
        self.assertTrue(all(name.endswith((".sty", ".cls")) for name in by_style))
        # Exactement l'inverse de `styles`.
        inverse: dict[str, list[str]] = {}
        for package in self.index["packages"]:
            for style in package["styles"]:
                inverse.setdefault(style, []).append(package["name"])
        self.assertEqual(by_style, inverse)

    def test_collection(self):
        expected = {
            "amsmath": "collection-latex",
            "beamer": "collection-latexrecommended",
            "biblatex": "collection-bibtexextra",
            "context-vim": "collection-context",
            "dvips": "collection-basic",
            "koma-script": "collection-latexrecommended",
            "kpathsea": "collection-basic",
            "latexmk": "collection-binextra",
            "luamplib": "collection-luatex",
            "multirow": "collection-latexextra",
            "pgf": "collection-pictures",
            "siunitx": "collection-mathscience",
            "jsclasses": None,
        }
        for name, collection in expected.items():
            self.assertEqual(self.packages[name]["collection"], collection, name)

    def test_deterministic(self):
        first = package_index.serialize(self.index)
        records = package_index.parse_tlpdb(self.text)
        random.Random(42).shuffle(records)
        self.assertEqual(package_index.serialize(package_index.build_index(records)), first)
        self.assertEqual(package_index.serialize(index_of(self.text)), first)


class ParserTest(unittest.TestCase):
    def test_relocated_paths_and_duplicates(self):
        # Base du dépôt CTAN : chemins RELOC/ ; un même fichier dans deux arbres compte une fois.
        index = index_of(
            "name foo\ncategory Package\nrelocated 1\nrunfiles size=3\n"
            " RELOC/tex/latex/foo/foo.sty\n RELOC/tex/generic/foo/foo.sty\n"
            " RELOC/tex/lualatex/foo/foo-lua.sty\n RELOC/tex/latex-dev/foo/foo-dev.sty\n"
            "\nname bar\ncategory Package\nrunfiles size=1\n texmf-dist/tex/latex/bar/foo.sty\n"
        )
        packages = {package["name"]: package for package in index["packages"]}
        self.assertEqual(packages["foo"]["styles"], ["foo-lua.sty", "foo.sty"])
        self.assertEqual(index["byStyle"]["foo.sty"], ["bar", "foo"])
        self.assertIsNone(index["texliveYear"])

    def test_only_runfiles_count(self):
        # Base installée avec la documentation : le .sty d'exemple des docfiles n'est pas fourni.
        index = index_of(
            "name foo\ncategory Package\ndocfiles size=2\n"
            " texmf-dist/doc/latex/foo/example.sty details=\"Example\" language=\"en\"\n"
            "srcfiles size=1\n texmf-dist/source/latex/foo/foo.dtx\n"
            "runfiles size=1\n texmf-dist/tex/latex/foo/foo.sty\n"
        )
        self.assertEqual(index["packages"][0]["styles"], ["foo.sty"])
        self.assertEqual(list(index["byStyle"]), ["foo.sty"])

    def test_unicode_and_odd_line_separators(self):
        index = index_of(
            "name ecrire\ncategory Package\nshortdesc Écriture « française »\n"
            "longdesc Saut\x0cde page et séparateur\n"
        )
        self.assertEqual(index["packages"][0]["shortdesc"], "Écriture « française »")
        self.assertIn("Écriture « française »", package_index.serialize(index))

    def test_records_without_blank_separator(self):
        index = index_of("name a\ncategory Package\nname b\ncategory Package\n")
        self.assertEqual([package["name"] for package in index["packages"]], ["a", "b"])

    def test_arch_package_detection(self):
        index = index_of(
            "name tool\ncategory Package\ndepend tool.ARCH\n\n"
            "name tool.x86_64-linux\ncategory Package\nbinfiles arch=x86_64-linux size=1\n"
            " bin/x86_64-linux/tool\n\n"
            "name tool.windows\ncategory Package\n\n"
            "name other.aarch64-linux\ncategory Package\n"
        )
        self.assertEqual([package["name"] for package in index["packages"]], ["tool"])

    def test_malformed_input(self):
        with self.assertRaisesRegex(package_index.PackageIndexError, "without a name"):
            package_index.parse_tlpdb("category Package\nshortdesc orphan\n")
        with self.assertRaisesRegex(package_index.PackageIndexError, "outside a file list"):
            package_index.parse_tlpdb("name a\ncategory Package\n texmf-dist/tex/latex/a/a.sty\n")
        with self.assertRaisesRegex(package_index.PackageIndexError, "duplicate package 'a'"):
            index_of("name a\ncategory Package\n\nname a\ncategory Package\n")

    def test_tlcore_selection(self):
        index = index_of(
            "name core-style\ncategory TLCore\nrunfiles size=1\n texmf-dist/tex/latex/cs/cs.sty\n\n"
            "name core-catalogue\ncategory TLCore\ncatalogue-license gpl2\n\n"
            "name core-alias\ncategory TLCore\ncatalogue ctan-alias\n\n"
            "name core-infra\ncategory TLCore\nrunfiles size=1\n texmf-dist/tex/generic/ci/ci.tex\n\n"
            "name core-tool\ncategory TLCore\ndepend core-tool.ARCH\ncatalogue-ctan /support/tool\n\n"
            "name core-tool.aarch64-linux\ncategory TLCore\ncatalogue-license gpl2\n\n"
            "name 00texlive.image\ncategory TLCore\ncatalogue-license lppl\n\n"
            "name collection-x\ncategory Collection\ncatalogue-ctan /x\n\n"
            "name scheme-x\ncategory Scheme\nrunfiles size=1\n texmf-dist/tex/latex/x/x.sty\n\n"
            "name plain-package\ncategory Package\n"
        )
        packages = {package["name"]: package for package in index["packages"]}
        self.assertEqual(
            sorted(packages),
            ["core-alias", "core-catalogue", "core-style", "core-tool", "plain-package"],
        )
        self.assertEqual(packages["core-style"]["category"], "TLCore")
        self.assertIsNone(packages["core-style"]["ctanUrl"])
        self.assertEqual(packages["core-catalogue"]["ctanUrl"], "https://ctan.org/pkg/core-catalogue")
        self.assertEqual(packages["core-alias"]["ctanUrl"], "https://ctan.org/pkg/ctan-alias")
        self.assertIsNone(packages["plain-package"]["ctanUrl"])
        self.assertEqual(index["byStyle"], {"cs.sty": ["core-style"]})

    def test_year(self):
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertEqual(index_of(text, texlive_year=2026)["texliveYear"], 2026)
        with self.assertRaisesRegex(package_index.PackageIndexError, "TeX Live 2026, expected 2025"):
            index_of(text, texlive_year=2025)
        self.assertEqual(index_of("name a\ncategory Package\n", texlive_year=2027)["texliveYear"], 2027)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_path_stdin_and_xz_give_identical_output(self):
        raw = FIXTURE.read_bytes()
        compressed = self.dir / "texlive.tlpdb.xz"
        compressed.write_bytes(lzma.compress(raw))
        results = [
            run_cli(str(FIXTURE)),
            run_cli(stdin=raw),
            run_cli("-", stdin=lzma.compress(raw)),
            run_cli(str(compressed)),
            run_cli(str(FIXTURE)),
        ]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual({result.stdout for result in results}, {results[0].stdout})
        index = json.loads(results[0].stdout)
        self.assertEqual(len(index["packages"]), 21)
        self.assertIn(b"21 packages", results[0].stderr)

    def test_output_file_and_checks(self):
        output = self.dir / "packages.json"
        result = run_cli(
            str(FIXTURE), "--output", str(output), "--texlive-year", "2026", "--min-packages", "21",
            "--require-style", "graphicx.sty", "--require-style", "beamer.cls",
            "--require-style", "scrartcl.cls", "--pretty",
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b"")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["texliveYear"], 2026)
        self.assertEqual([path.name for path in self.dir.iterdir()], ["packages.json"])

    def test_failures_write_nothing(self):
        output = self.dir / "packages.json"
        cases = [
            (["--min-packages", "22"], "only 21 packages indexed"),
            (["--require-style", "nonexistent.sty"], "missing from the index: nonexistent.sty"),
            (["--texlive-year", "2025"], "expected 2025"),
        ]
        for extra, message in cases:
            with self.subTest(extra=extra):
                result = run_cli(str(FIXTURE), "--output", str(output), *extra)
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr.decode())
                self.assertFalse(output.exists())
        result = run_cli(str(self.dir / "missing.tlpdb"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("package-index: error:", result.stderr.decode())
        result = run_cli(stdin=b"\xfd7zXZ\x00truncated")
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
