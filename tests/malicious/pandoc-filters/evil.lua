-- Filtre du projet : ne doit jamais s'exécuter (marqueur assemblé à l'exécution).
local marker = 'KX-EVIL-' .. 'FILTER'
local handle = io.open('pwned.txt', 'w')
if handle then handle:write(marker) handle:close() end
os.execute('touch pwned-exec.txt')
function Str() return pandoc.Str(marker) end
