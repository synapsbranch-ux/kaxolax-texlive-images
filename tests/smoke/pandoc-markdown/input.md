---
title: Conversion Markdown
author: Kaxolax
---

# Introduction

Un paragraphe avec de l'*emphase*, du **gras**, du `code`, un lien vers
[pandoc](https://pandoc.org) et une note[^note]. Accents : élève, cœur, « guillemets ».

[^note]: Le texte de la note.

## Listes

- premier point
- second point
  1. sous-point numéroté
  2. autre sous-point
- [x] tâche faite

## Mathématiques

En ligne $e^{i\pi} + 1 = 0$, et centrée :

$$
\int_0^1 x^2 \, dx = \frac{1}{3}
$$

## Tableau

| Moteur   | Unicode | Lua |
|----------|:-------:|----:|
| pdfLaTeX | non     | non |
| LuaLaTeX | oui     | oui |

: Moteurs disponibles

## Code

```python
def hello(name: str) -> str:
    return f"Bonjour {name}"
```

> Une citation
> sur deux lignes.

## Images

![Une figure du projet](figures/plot.png){width=40%}

![Une image intégrée](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAEElEQVR4nGM4IScHRwzEcQCxYxBBO0tjggAAAABJRU5ErkJggg==)

Fin du document~~barré~~.
