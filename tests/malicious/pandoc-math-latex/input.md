---
title: 'Formules $\immediate\write18{touch title.txt}$'
header-includes: |
  $\immediate\write18{touch yaml.txt}\directlua{os.execute("touch yaml-lua.txt")}$
---

# LaTeX dans les formules

Le texte est échappé, pas les formules : $\immediate\write18{touch inline.txt}$.

$$\directlua{texio.write_nl("KX-LUA-EXEC=" .. tostring(os.execute("touch lua.txt")))}$$

$$\catcode`\%=12 \immediate\write18{touch display.txt}$$

Pour finir, une lecture de fichier : $\input{/etc/passwd}$.
