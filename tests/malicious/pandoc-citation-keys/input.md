# Clés de citation piégées

La syntaxe `@{…}` de pandoc accepte n'importe quel texte comme clé, recopié tel quel dans
`\autocite{…}` : [@{x\input{/etc/passwd}y}], @{z\immediate\write18{touch pwned.txt}}, [@k%z, p. 1]
et [@{@@HOST_CANARY@@}]. Une clé ordinaire reste une citation : [@knuth84].
