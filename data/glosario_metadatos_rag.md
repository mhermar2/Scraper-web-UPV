# Glosario de metadatos — base documental UPV para RAG

> **Este fichero no es un documento del corpus.** No debe indexarse ni
> recuperarse por similitud semántica junto con el resto de `.md` de
> `data/processed/` — su lugar natural es como **contexto fijo en el
> system prompt** de la aplicación RAG/chatbot que se construya sobre
> esta base documental, entregado siempre junto con lo recuperado, no
> dependiente de que se recupere por similitud. Vive en la raíz de
> `data/` (hermano de `raw/`/`processed/`), no dentro de `processed/`,
> precisamente para quedar fuera de esa carpeta si el pipeline de
> ingesta indexa `data/processed/` de forma recursiva.

## Qué es esta base documental

`data/processed/` contiene un corpus en Markdown extraído de la web
oficial de la Universitat Politècnica de València (upv.es y
subdominios), organizado por categorías temáticas (admisión, estudios,
investigación, institución, servicios, organización, comunidad
universitaria, orientación, contacto, rankings). Cada `.md` lleva una
cabecera YAML con metadatos estructurados que permiten entender qué es
cada documento, de qué otro documento depende y cómo se relaciona con
el resto del corpus. Este glosario explica ese esquema de metadatos.

`data/raw/` contiene los JSON intermedios que generaron ese corpus
(catálogos de titulaciones, entidades, enlaces...) — no son documentos
pensados para recuperación, son la materia prima del proceso de
extracción; tampoco deberían indexarse como contenido consultable.

## Esquema de metadatos (cabecera YAML de cada `.md`)

```yaml
---
fuente: UPV
url: <url del documento>
categoria: <admision|estudios|investigacion|institucion|servicios|organizacion|comunidad_upv|orientacion|contacto|rankings>
nivel: <subcarpeta dentro de categoria, si existe>
tipo_documento: <resumen|seccion|recurso>
tipo_recurso: <informacion|servicio|calendario|matricula|faq|ayudas|...>
resumen: <URL del documento "resumen" del que cuelga>
seccion: <slug interno de la subsección>
titulo: <título legible del documento>
descripcion: ""
actualizado: <YYYY-MM-DD>

# Solo en fichas de titulación (estudios/master, estudios/doctorado):
acronimo: <acrónimo>
campus: <campus>
modalidad: <modalidad>
centro: <centro>
rama: <rama>
---
```

### Campo por campo

- **`fuente`** — siempre `UPV`. De dónde procede la información (útil si
  en el futuro se añaden fuentes de otros organismos).
- **`url`** — la URL real de la página de la UPV de la que se extrajo el
  documento. Es la referencia canónica: si dos documentos comparten la
  misma `url`, son el mismo documento (esto es lo que usa `resumen` para
  enlazar a otro documento del corpus, ver más abajo). Útil también para
  citar la fuente original en una respuesta o para que el usuario
  verifique la información en la web oficial.
- **`categoria`** — el área temática de más alto nivel a la que
  pertenece el documento. Coincide exactamente con la carpeta de primer
  nivel dentro de `data/processed/`. Valores posibles: `admision`,
  `estudios`, `investigacion`, `institucion`, `servicios`,
  `organizacion`, `comunidad_upv`, `orientacion`, `contacto`,
  `rankings`.
- **`nivel`** — la subcategoría dentro de `categoria`, si existe.
  Coincide con la subcarpeta real dentro de `data/processed/<categoria>/`.
  No todas las categorías tienen subcarpetas (`servicios`, `rankings`,
  `orientacion` y `contacto` son planas, sin `nivel`). Ver la tabla de
  categorías/niveles más abajo para el listado completo.
- **`tipo_documento`** — el rol del documento dentro de su categoría/nivel.
  Tres valores posibles, explicados en detalle en la sección siguiente:
  `resumen`, `seccion`, `recurso`.
- **`tipo_recurso`** — una clasificación más fina del CONTENIDO de un
  recurso (normalmente solo presente en documentos `tipo_documento:
  recurso`, aunque no es estrictamente exclusivo). No es una lista
  cerrada — se ha ido ampliando según lo que aparecía en cada sección,
  valores ya usados en el corpus: `informacion` (el más genérico, la
  mayoría de recursos), `servicio`, `calendario`, `matricula`, `faq`,
  `ayudas`, `admision`, `curso`, `master`, `estudios`, `programas`,
  `ranking`, `destacado`, `diploma_especializacion`,
  `diploma_experto`, `diploma_extension`. Útil para filtrar por tipo de
  consulta (ej. priorizar `faq` si la pregunta suena a duda frecuente,
  o `calendario`/`matricula` si pregunta por fechas o plazos).
- **`resumen`** — la URL del documento ancestro del que depende este
  documento (ver tabla de presencia más abajo). Es siempre una URL, no
  un identificador interno: apunta al documento del corpus cuyo propio
  campo `url` coincide con este valor. Normalmente es la página
  resumen/índice de toda la categoría o nivel — pero en los documentos
  generados por el programa de descubrimiento de contenido nuevo (ver
  `profundidad` más abajo) puede apuntar a otro `recurso` (la página
  concreta en la que se encontró el enlace), no solo a un `resumen`;
  para llegar hasta el resumen de la categoría en esos casos hace falta
  seguir la cadena de `resumen` más de un salto. Sirve para reconstruir
  la jerarquía completa de una categoría/sección a partir de cualquier
  documento suelto, y para decidir si conviene recuperar también el
  documento del que depende cuando se recupera uno más concreto (más
  contexto general de dónde encaja).
- **`seccion`** — un slug interno (no una URL) que identifica la
  subsección concreta a la que pertenece un recurso dentro de su
  `nivel` (ej. la carpeta en la que vive, o una agrupación temática del
  propio catálogo de origen). A menudo no existe una página real de la
  web que represente esa subsección — es una agrupación editorial hecha
  al extraer el contenido, de ahí que sea un slug y no una URL. Solo
  presente en documentos `tipo_documento: recurso`.
- **`titulo`** — el título legible del documento, pensado para mostrarse
  al usuario final (ej. como fuente citada en una respuesta).
- **`descripcion`** — resumen corto en 1-2 frases del contenido del
  documento. Puede estar vacío (`""`) si no se ha rellenado todavía —
  no asumir que su ausencia significa que el documento no tiene
  contenido, solo que no se ha resumido aparte.
- **`actualizado`** — la fecha en la que se extrajo el contenido de la
  web (formato `YYYY-MM-DD`, a veces solo `YYYY-MM`), NO la fecha de
  publicación o última modificación del contenido en la propia web de
  la UPV. Sirve para saber cuánto puede haberse desactualizado un
  documento respecto a la web real.
- **`acronimo`, `campus`, `modalidad`, `centro`, `rama`** — solo
  presentes en fichas de titulación (`estudios/master`,
  `estudios/doctorado`, y `estudios/grado` cuando aplica). Datos
  estructurados propios de una titulación universitaria: acrónimo
  oficial, campus donde se imparte, modalidad (presencial/online/mixta,
  cuando se conoce), centro responsable y rama de conocimiento. Útil
  para filtrar titulaciones por estos criterios sin tener que analizar
  el texto libre del documento.
- **`profundidad`** — solo presente en documentos generados por el
  programa de descubrimiento de contenido nuevo (`src/descubrimiento.py`),
  ausente en el resto del corpus. Un entero ≥ 1: cuántos saltos de
  enlace separan a este documento del contenido curado originalmente
  (1 = enlazado directamente desde un documento sin este campo, 2 =
  enlazado desde uno de profundidad 1, etc.). Como estos documentos no
  pasan por un extractor específico de su plantilla, sino por una
  extracción genérica, cuanto mayor sea `profundidad` más razonable es
  esperar algo más de ruido residual en el contenido (menús o pies de
  página no filtrados del todo) — útil como señal aproximada de
  confianza/relevancia, no como filtro estricto.

## `tipo_documento`: resumen, sección y recurso

Cada categoría/nivel del corpus sigue una jerarquía de hasta tres
niveles de documentos:

| `tipo_documento` | Qué es | `resumen` | `seccion` |
|---|---|---|---|
| `resumen` | Página raíz/índice de una categoría o nivel, de la que cuelgan las demás (ej. `institucion.md`, `estudios/grado/grado.md`) | no | no |
| `seccion` | Documento con texto propio sustancial que agrupa varios recursos relacionados dentro de un nivel, pero no es la raíz de toda la categoría | sí (URL del resumen del que cuelga) | no |
| `recurso` | El documento más específico: una página o PDF concreto | sí (URL del resumen, aunque haya que saltarse un nivel intermedio sin documento propio; en contenido de descubrimiento — ver `profundidad` — puede ser la URL de otro `recurso` en vez del resumen de la categoría) | sí (slug de la subsección) |

Por qué importa esta distinción para un sistema de recuperación:
- Un **`resumen`** da la visión general de una categoría entera — útil
  cuando la pregunta del usuario es amplia o ambigua ("¿qué másteres
  ofrece la UPV?", "¿cómo está organizada la UPV?").
- Un **`recurso`** da el detalle más concreto — útil cuando la pregunta
  es específica ("¿cuál es el plazo de matrícula del máster X?").
- Recuperar un `recurso` sin su `resumen` puede dejar al sistema sin
  contexto de en qué categoría/sección encaja ese detalle; seguir el
  campo `resumen` hacia el documento que tiene esa misma `url` permite
  añadir ese contexto general cuando haga falta, sin tener que indexarlo
  todo junto de antemano.
- Evitar recuperar `resumen` y varios `recurso` de la misma sección a la
  vez cuando son redundantes entre sí (el resumen ya suele enlazar/listar
  los recursos por título).

## Categorías y niveles (subcarpetas) reales del corpus

`categoria`/`nivel` coinciden exactamente con la carpeta/subcarpeta real
dentro de `data/processed/` — no hay valores inventados fuera de esta
lista:

| `categoria` | `nivel` (subcarpetas) |
|---|---|
| `admision` | `grado`, `master`, `doctorado`, `internacional` |
| `estudios` | `grado`, `master`, `doctorado`, `formacion_permanente` |
| `investigacion` | `estructuras`, `iniciativas_idi`, `innovacion` |
| `institucion` | `organos_gobierno`, `publicaciones_oficiales`, `upv_al_detalle`, `estrategia_upv_sirve`, `sindicatura` |
| `organizacion` | `escuelas_facultades`, `departamentos`, `sostenibilidad` |
| `comunidad_upv` | `estudiante` (con `becas_ayudas` anidada dentro, `estudiante/becas_ayudas`), `ptgas_pdi_pi` |
| `servicios` | *(sin subcarpeta — no lleva `nivel`)* |
| `rankings` | *(sin subcarpeta — no lleva `nivel`)* |
| `orientacion` | *(sin subcarpeta — no lleva `nivel`)* |
| `contacto` | *(sin subcarpeta — no lleva `nivel`)* |

Un documento `resumen` que vive directamente en la carpeta de
`categoria` (sin subcarpeta, ej. `institucion.md`) no lleva `nivel`. Uno
que vive dentro de una subcarpeta (ej. un documento en `admision/master/`)
sí lo lleva con normalidad, aunque sea de tipo `resumen`.

## Notas para quien construya el chatbot

- El contenido en español mantiene tildes y ñ con normalidad; solo los
  NOMBRES de los campos YAML están sin acentos (`titulo`, `acronimo`,
  no `título`/`acrónimo`).
- Este glosario documenta el esquema tal y como está aplicado en todo
  el corpus (sitemap de la UPV cubierto por completo a fecha de esta
  extracción) — si en el futuro se añade contenido nuevo con este mismo
  proceso de extracción, debería seguir el mismo esquema.
- Algunos recursos son notas breves en vez de contenido completo,
  cuando el enlace original llevaba a una aplicación dinámica sin
  contenido accesible sin iniciar sesión (intranet, PoliformaT,
  automatrícula...) o a un enlace roto en la propia web de la UPV — en
  ambos casos el documento lo indica explícitamente en su propio texto,
  con la URL original para que el usuario pueda consultarla
  directamente si tiene acceso.
