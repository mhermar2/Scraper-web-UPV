# Base documental UPV para RAG

Base de datos en Markdown extraído de la web oficial de la Universitat
Politècnica de València ([upv.es](https://www.upv.es)), pensado para
alimentar un sistema de *Retrieval-Augmented Generation* (RAG) o
chatbot institucional. Trabajo de Fin de Grado de Ingeniería de
Tecnologías y Servicios de Telecomunicación (UPV).

Cubre las secciones oficiales del sitio (admisión, estudios,
investigación, institución, organización, servicios, comunidad
universitaria, orientación, contacto y rankings), extraídas y
normalizadas a un formato homogéneo con metadatos estructurados.

## Estructura del repositorio

```
src/
├── config.py            # rutas de datos y constantes compartidas
├── common.py             # helpers HTTP y de checkpoint compartidos
├── actualizar.py         # orquestador interactivo: actualiza data/processed/
├── descubrimiento.py     # descubre y genera contenido nuevo no cubierto todavia
├── extractores/          # un extractor por sección/categoría del sitemap,
│                         #   más motor_limpieza.py (motor de limpieza compartido)
└── crawlers/             # crawler genérico y librería de soporte de descubrimiento.py

data/
├── raw/                  # JSON intermedios de cada extractor (no son contenido
│                         #   consultable, son la materia prima del proceso).
│                         #   Incluye descubrimiento_urls.json, el fichero de
│                         #   seguimiento de descubrimiento.py: registra cada URL
│                         #   conocida (si ya tiene .md, de qué página cuelga, y a
│                         #   cuántos saltos de enlace del contenido curado
│                         #   original está) para poder avanzar de forma
│                         #   incremental entre ejecuciones sin repetir trabajo.
├── processed/            # el corpus en sí — el Markdown que consume el RAG
├── glosario_metadatos_rag.md   # esquema de metadatos, pensado como contexto
│                         #   fijo del system prompt de la aplicación RAG
└── legacy/                # copias de seguridad de contenido antiguo, guardadas
                          #   automáticamente antes de sobrescribir una sección
```

`data/processed/` está organizado según el
[mapa del sitio oficial de la UPV](https://www.upv.es/otros/mapa-web-es.html),
no según qué extractor generó cada fichero — cada categoría es una
carpeta de primer nivel (`admision/`, `estudios/`, `investigacion/`...)
con subcarpetas por nivel donde corresponde (`estudios/master`,
`estudios/doctorado`...).

## Requisitos

- Python 3.11+
- Dependencias listadas en `requirements.txt`

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

## Uso

### Actualizar el corpus existente

```bash
python src/actualizar.py
```

Menú interactivo que lista todas las secciones cubiertas, agrupadas por
categoría. Permite elegir una, varias o todas ("todas" o números
separados por comas). Antes de sobrescribir cualquier sección con
contenido ya generado, hace una copia de seguridad en `data/legacy/` y
pide confirmación; al terminar, distingue si hubo contenido nuevo de
verdad o solo un refresco de la fecha de comprobación, y pregunta antes
de comitear cualquier cambio.

### Descubrir contenido nuevo

```bash
python src/descubrimiento.py
```

Complementa a `actualizar.py`: en vez de refrescar secciones ya
cubiertas, busca páginas de upv.es enlazadas desde el corpus existente
que todavía no tienen ficha propia, y ofrece generarlas — en lotes
pequeños, con confirmación explícita antes de escribir nada. Avanza de
forma incremental (una "profundidad" de enlaces cada vez, ampliable en
sucesivas ejecuciones), no de una sola pasada.

## Formato de los documentos

Cada `.md` de `data/processed/` lleva una cabecera YAML con metadatos
estructurados (categoría, tipo de documento, de qué otro documento
depende, título, fecha de extracción...). El esquema completo, pensado
para explicarse como contexto fijo a un LLM en una aplicación RAG, está
documentado en [`data/glosario_metadatos_rag.md`](data/glosario_metadatos_rag.md).

## Limitaciones conocidas

- La web de la UPV combina varias plantillas y CMS distintos según la
  sección (WordPress moderno, un backend clásico Oracle Portal/PL-SQL,
  microsites independientes...); los extractores contemplan las
  variantes ya identificadas, pero contenido en una plantilla no vista
  antes puede necesitar ajustes.
- El backend clásico (`pls/oalu/...`, usado por ejemplo en
  Asignaturas/Competencias/Profesorado de grado y máster) puede
  devolver errores `503`/timeouts bajo uso intensivo sostenido — no es
  un fallo del extractor, sino un límite del lado del servidor.
- Varios subdominios quedan deliberadamente fuera de alcance por
  requerir sesión de usuario o no ser contenido público indexable:
  intranet, PoliformaT, automatrícula, RiuNet, correo, sede
  electrónica, entre otros.
