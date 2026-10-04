-- Filtre Lua contrôlé de la conversion Markdown → LaTeX de Tex.ink (seul filtre jamais passé à
-- pandoc ; aucun filtre ne vient du projet ni de la demande).
--
-- Les filtres Lua ne sont pas couverts par `--sandbox` : ce code peut lire tout fichier et ouvrir
-- le réseau. Il n'appelle donc `pandoc.mediabag.fetch` que sur une URI `data:` (décodée en
-- mémoire), et n'écrit que deux noms constants du répertoire courant : `media/<sha1>.<ext>` et
-- `texink-report.json`. Aucune valeur du document ne sert de chemin d'écriture.
--
-- Entrée : `texink-convert.json` (écrit par l'agent dans le répertoire courant) :
--   sourceDir   répertoire du fichier Markdown dans le projet ('' : racine)
--   graphicsDir répertoire depuis lequel LaTeX résout les images (celui du document principal)
--   mediaDir    répertoire du projet où l'agent rangera les images extraites
--   maxEmbedded nombre maximal d'images `data:` extraites
--   marker      jeton aléatoire des marqueurs de début et de fin du corps
--   fragment    vrai : titre, auteurs, date et résumé retirés des métadonnées (fragment)
-- Sortie : `texink-report.json` (titre, images rencontrées et leur traitement, clés de citation
-- gardées et refusées).
--
-- Citations : pandoc écrit les clés telles quelles dans `\citep{…}` / `\autocite{…}` (`--natbib`,
-- `--biblatex`), même avec la syntaxe `@{…}` qui accepte n'importe quel texte : une clé hors de
-- l'alphabet sûr (lettres, chiffres, `_:.-+/`) injecterait du LaTeX. La citation entière redevient
-- alors du texte (échappé par le rédacteur) et la clé est signalée.

local OPTIONS_FILE = 'texink-convert.json'
local REPORT_FILE = 'texink-report.json'
local MEDIA_DIR = 'media'
-- Images intégrées acceptées : celles que pdfLaTeX, XeLaTeX et LuaLaTeX incluent sans conversion.
local EMBEDDED_TYPES = {
  ['image/png'] = 'png',
  ['image/jpeg'] = 'jpg',
  ['application/pdf'] = 'pdf',
}
local MAX_REPORTED_IMAGES = 500
local MAX_REPORTED_CITATIONS = 500
-- Clé de citation recopiée dans le LaTeX : alphabet de BibTeX, sans caractère actif pour TeX.
local SAFE_CITATION_KEY = '^[%w_][%w_:%.%-%+/]*$'
local MAX_CITATION_KEY = 200

local function read_options()
  local handle = assert(io.open(OPTIONS_FILE, 'rb'), 'missing ' .. OPTIONS_FILE)
  local text = handle:read('a')
  handle:close()
  local options = pandoc.json.decode(text, false)
  assert(type(options) == 'table', 'invalid ' .. OPTIONS_FILE)
  for _, key in ipairs({ 'sourceDir', 'graphicsDir', 'mediaDir', 'marker' }) do
    assert(type(options[key]) == 'string', 'invalid option ' .. key)
  end
  assert(options.marker:match('^%x+$'), 'invalid marker')
  local max_embedded = options.maxEmbedded
  assert(type(max_embedded) == 'number' and max_embedded >= 0, 'invalid option maxEmbedded')
  options.maxEmbedded = math.floor(max_embedded)
  return options
end

local options = read_options()
local images = {}
local embedded = 0
local written = {}
local citations = {}
local cited = {}
local rejected_citations = {}
local rejected_cited = {}

-- Segments d'un chemin relatif normalisé ; nil s'il sort de la racine du projet.
local function normalize(path)
  local segments = {}
  for segment in path:gmatch('[^/]+') do
    if segment == '..' then
      if #segments == 0 then
        return nil
      end
      table.remove(segments)
    elseif segment ~= '.' then
      table.insert(segments, segment)
    end
  end
  return segments
end

local function join(dir, path)
  if dir == '' then
    return path
  end
  return dir .. '/' .. path
end

-- Chemin de `target` (chemin du projet) vu depuis le répertoire `from` (chemin du projet).
local function relative(from, target)
  local base = normalize(from) or {}
  local parts = normalize(target) or {}
  local common = 0
  while common < #base and common < #parts - 1 and base[common + 1] == parts[common + 1] do
    common = common + 1
  end
  local result = {}
  for _ = common + 1, #base do
    table.insert(result, '..')
  end
  for index = common + 1, #parts do
    table.insert(result, parts[index])
  end
  return table.concat(result, '/')
end

local function percent_decode(text)
  return (text:gsub('%%(%x%x)', function(hex)
    return string.char(tonumber(hex, 16))
  end))
end

local function record(entry)
  if #images < MAX_REPORTED_IMAGES then
    table.insert(images, entry)
  end
end

-- Remplacement d'une image inutilisable : son texte alternatif.
local function fallback(image)
  return pandoc.Span(image.caption, { class = 'texink-missing-image' })
end

local function embedded_image(image)
  local ok, mime, contents = pcall(pandoc.mediabag.fetch, image.src)
  local media_type = ok and type(mime) == 'string' and mime:match('^[^;]+') or nil
  local extension = media_type and EMBEDDED_TYPES[media_type:lower()]
  if not extension or type(contents) ~= 'string' then
    record({ source = 'data:', kind = 'rejected', reason = 'unsupported_type' })
    return fallback(image)
  end
  local name = pandoc.utils.sha1(contents) .. '.' .. extension
  -- Plafond des fichiers écrits : une image déjà extraite (même contenu) ne coûte rien.
  if not written[name] and embedded >= options.maxEmbedded then
    record({ source = 'data:', kind = 'rejected', reason = 'too_many_embedded' })
    return fallback(image)
  end
  if not written[name] then
    local handle = assert(io.open(MEDIA_DIR .. '/' .. name, 'wb'))
    handle:write(contents)
    handle:close()
    written[name] = true
    embedded = embedded + 1
  end
  local path = join(options.mediaDir, name)
  record({ source = 'data:' .. media_type, kind = 'embedded', path = path })
  image.src = relative(options.graphicsDir, path)
  return image
end

function Image(image)
  local src = image.src
  if src:sub(1, 5) == 'data:' then
    return embedded_image(image)
  end
  if src:match('^%a[%w+.-]*:') then
    -- Image distante : jamais téléchargée (aucun réseau) ; elle devient un lien.
    record({ source = src, kind = 'remote' })
    return pandoc.Link(image.caption, src)
  end
  if src:sub(1, 1) == '/' or src:find('\\', 1, true) then
    record({ source = src, kind = 'rejected', reason = 'absolute_path' })
    return fallback(image)
  end
  local decoded = percent_decode((src:gsub('[?#].*$', '')))
  local segments = normalize(join(options.sourceDir, decoded))
  if not segments or #segments == 0 then
    record({ source = src, kind = 'rejected', reason = 'outside_project' })
    return fallback(image)
  end
  local path = table.concat(segments, '/')
  record({ source = src, kind = 'project', path = path })
  image.src = relative(options.graphicsDir, path)
  return image
end

local function add_unique(list, seen, value)
  if not seen[value] and #list < MAX_REPORTED_CITATIONS then
    seen[value] = true
    table.insert(list, value)
  end
end

-- Citation `[@clé]` : gardée (commande `\cite…` du rédacteur) si toutes ses clés sont sûres,
-- sinon remplacée par son texte d'origine.
function Cite(cite)
  for _, citation in ipairs(cite.citations) do
    local key = citation.id
    if #key > MAX_CITATION_KEY or not key:match(SAFE_CITATION_KEY) then
      add_unique(rejected_citations, rejected_cited, key:sub(1, MAX_CITATION_KEY))
      return pandoc.Span(cite.content, { class = 'texink-rejected-citation' })
    end
  end
  for _, citation in ipairs(cite.citations) do
    add_unique(citations, cited, citation.id)
  end
  return nil
end

function Pandoc(doc)
  local title = doc.meta.title and pandoc.utils.stringify(doc.meta.title) or nil
  if options.fragment == true then
    for _, key in ipairs({ 'title', 'subtitle', 'author', 'date', 'abstract', 'thanks' }) do
      doc.meta[key] = nil
    end
  end
  doc.blocks:insert(1, pandoc.RawBlock('latex', '%TEXINK-BODY-BEGIN-' .. options.marker))
  doc.blocks:insert(pandoc.RawBlock('latex', '%TEXINK-BODY-END-' .. options.marker))
  local handle = assert(io.open(REPORT_FILE, 'wb'))
  handle:write(pandoc.json.encode({
    title = title or pandoc.json.null,
    images = pandoc.List(images),
    citations = pandoc.List(citations),
    rejectedCitations = pandoc.List(rejected_citations),
  }))
  handle:close()
  return doc
end

return {
  { Image = Image, Cite = Cite },
  { Pandoc = Pandoc },
}
