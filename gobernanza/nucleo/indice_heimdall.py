"""Índice nativo de Heimdall sobre una imagen privada de solo lectura.

Derivado de gobernanza/herramientas/indice.py del motor gobernanza-hook en
0e3f6308a67fdb21d45fa0570975029fab2d9380, fijado por Heimdall. Conserva sus
parsers, cotejo y render; la raíz de los datos la recibe del servicio.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

PREFIJOS_CONOCIDOS = ("spec_", "enmienda_")

# El spec al que la enmienda modifica. Un mismo concepto con seis nombres:
# el repo los usó todos y ninguno es incorrecto.
CAMPOS_DESTINO = (
    "enmienda a", "enmienda al", "spec destino", "espec destino", "espec base",
    "espec", "especacion madre", "especificacion madre", "modifica",
)
# Lo que la enmienda roza sin ser su destino principal.
CAMPOS_SECUNDARIOS = ("toca ademas", "toca", "alcance", "afecta")


def sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def normaliza_campo(campo: str) -> str:
    """`**Enmiendas incorporadas** (2026-08-21)` → `enmiendas incorporadas`."""
    campo = campo.replace("*", "").replace("`", "").replace(":", "")
    campo = re.sub(r"\(.*?\)", "", campo)
    return sin_acentos(campo).strip().lower()


# ── lectura de cabeceras, en sus tres formas ──────────────────────────────────

RE_FILA_TABLA = re.compile(r"^\|(?!\s*[-:\s|]+\|?\s*$)(.+)\|\s*$")
RE_CAMPO_NEGRITA = re.compile(r"^\*\*(?P<campo>[^*]+?)\*\*\s*:?\s*(?P<valor>.*)$")


RE_ENCABEZADO = re.compile(r"^#{2,6}\s+(\d+(?:\.[0-9A-Za-z]+)*)[ .]")
RE_PUNTO = re.compile(r"^\s{0,3}(\d{1,2})\.\s")
RE_REFERENCIA = re.compile(r"§\s?(\d+(?:\.[0-9A-Za-z]+)*(?:\s\d+)?)")


def normaliza_seccion(ref: str) -> str:
    """`0.B 11`, `8 punto 5` y `8.5` son la misma cosa escrita de tres modos."""
    ref = re.sub(r"\s*punto\s*", ".", ref, flags=re.IGNORECASE)
    return re.sub(r"[\s.]+", ".", ref.strip()).rstrip(".")


def indice_de_secciones(texto: str) -> set[str]:
    """Las § que un documento tiene de verdad.

    No basta con los encabezados. Este repo cita **puntos numerados** dentro de
    una sección —`§8.1` es el punto 1 de «8. Trabajo abierto», `§3.1.5` el punto
    5 de «3.1 Fidelidad tipográfica»— y es un estilo legítimo, usado en todo el
    corpus. Un verificador que sólo mire encabezados declara rota una cita
    correcta, que es peor que no verificar nada.
    """
    sesiones: set[str] = set()
    actual: str | None = None
    for linea in texto.splitlines():
        m = RE_ENCABEZADO.match(linea)
        if m:
            actual = m.group(1).rstrip(".")
            sesiones.add(actual)
            # `3.1` implica que `3` existe.
            partes = actual.split(".")
            for k in range(1, len(partes)):
                sesiones.add(".".join(partes[:k]))
            continue
        m = RE_PUNTO.match(linea)
        if m and actual:
            sesiones.add(f"{actual}.{m.group(1)}")
    return sesiones


def cuerpo_sin_cabecera(ruta: Path) -> str:
    """El texto del documento por debajo de su tabla de cabecera."""
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    inicio = next((i for i, l in enumerate(lineas) if l.startswith("|")), None)
    if inicio is None:
        return "\n".join(lineas)
    fin = inicio
    while fin + 1 < len(lineas) and lineas[fin + 1].startswith("|"):
        fin += 1
    return "\n".join(lineas[fin + 1:])


def lee_campos(ruta: Path) -> tuple[str, list[tuple[str, str]], str]:
    """(título, campos, preámbulo) — el preámbulo es todo lo previo a la §1."""
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    titulo = ruta.stem
    campos: list[tuple[str, str]] = []
    preambulo: list[str] = []
    campo_abierto: str | None = None

    for linea in lineas:
        cruda = linea.rstrip()
        desnuda = cruda.strip()

        if desnuda.startswith("## "):
            break
        if desnuda.startswith("# "):
            titulo = desnuda[2:].strip()
            continue

        preambulo.append(cruda)

        m = RE_FILA_TABLA.match(desnuda)
        if m:
            campo_abierto = None
            partes = [p.strip() for p in m.group(1).split("|")]
            if len(partes) >= 2 and normaliza_campo(partes[0]) != "campo":
                campos.append((normaliza_campo(partes[0]), partes[1]))
            continue

        m = RE_CAMPO_NEGRITA.match(desnuda)
        if m:
            campo_abierto = normaliza_campo(m.group("campo"))
            campos.append((campo_abierto, m.group("valor").strip()))
            continue

        # Un campo en negrita puede continuar en las líneas siguientes hasta un
        # renglón en blanco o el siguiente campo: la enmienda 26 escribe así su
        # Estado, en seis renglones.
        if campo_abierto and desnuda:
            campo, valor = campos[-1]
            campos[-1] = (campo, f"{valor} {desnuda}".strip())
        else:
            campo_abierto = None

    return titulo, campos, "\n".join(preambulo)


def primer_valor(campos: list[tuple[str, str]], *prefijos: str) -> str:
    for prefijo in prefijos:
        for campo, valor in campos:
            if campo.startswith(prefijo):
                return valor
    return ""


# ── extracción de relaciones ──────────────────────────────────────────────────

RE_SPEC = re.compile(r"(spec_[a-z0-9-]+)\.md")
RE_ENMIENDA_TEXTO = re.compile(r"enmiendas?[_\s]+(\d{1,3})", re.IGNORECASE)
# Las filas viejas de `spec_sistema-visual.md` citan por número desnudo,
# separadas por `·`:  «13 — `Pestanas` … · 18 — `Icono` …».
RE_ENMIENDA_NUMERO = re.compile(r"^\s*\*{0,2}(\d{1,3})\s*—")


def encabeza_segmento(segmento: str) -> int | None:
    """La enmienda que encabeza un segmento del catálogo, o None."""
    m = RE_ENMIENDA_NUMERO.match(segmento)
    if m:
        return int(m.group(1))
    m = RE_ENMIENDA_TEXTO.search(segmento)
    return int(m.group(1)) if m else None


def clasifica_estado(texto: str) -> str:
    t = sin_acentos(texto).lower()
    if "incorporad" in t:
        return "Incorporada"
    if "diferida" in t:
        return "Diferida"
    if "borrador" in t:
        return "Borrador"
    if "propuesta" in t:
        return "Propuesta"
    if "validad" in t or "aprobad" in t:
        return "Validada"
    return "Sin estado"


def carga_enmiendas(raiz: Path) -> dict[str, dict]:
    fichas = {}
    for ruta in sorted(path for root in (raiz / "sdd", raiz / "gobernanza/sdd") for path in root.glob("enmienda_*.md")):
        titulo, campos, preambulo = lee_campos(ruta)
        m = re.match(r"enmienda_(\d{1,3})_", ruta.name)

        estado_crudo = primer_valor(campos, "estado")
        principal = primer_valor(campos, *CAMPOS_DESTINO)
        secundario = primer_valor(campos, *CAMPOS_SECUNDARIOS)

        specs = sorted(set(RE_SPEC.findall(principal)))
        toca = sorted(set(RE_SPEC.findall(secundario)) - set(specs))
        # La enmienda 73 no declara campos: dice su destino en prosa. Antes de
        # llamarla incompleta, se lee el preámbulo.
        inferido = False
        if not specs and not toca:
            specs = sorted(set(RE_SPEC.findall(preambulo)))
            inferido = bool(specs)

        fichas[ruta.name] = {
            "archivo": ruta.name,
            "enlace": os.path.relpath(ruta, raiz / "sdd"),
            "numero": int(m.group(1)) if m else None,
            "titulo": titulo,
            "estado": clasifica_estado(estado_crudo or preambulo),
            "declara_estado": bool(estado_crudo),
            "specs": specs,
            "toca": toca,
            "destino_inferido": inferido,
            "colision_declarada": "colision" in sin_acentos(
                primer_valor(campos, "numero")
            ).lower(),
            "producto": primer_valor(campos, "producto"),
            "frente": primer_valor(campos, "frente"),
            "campos": campos,
        }
    return fichas


def carga_specs(raiz: Path) -> dict[str, dict]:
    """Un spec declara incorporación en `Enmiendas incorporadas` o en `Estado`.

    Sólo esos dos campos cuentan: `Depende de` cita enmiendas de OTROS specs
    («spec_autenticacion.md, con enmienda 08 incorporada») y tomarlas por
    propias sería atribuirse el trabajo del vecino.
    """
    fichas = {}
    for ruta in sorted(path for root in (raiz / "sdd", raiz / "gobernanza/sdd") for path in root.glob("spec_*.md")):
        titulo, campos, _ = lee_campos(ruta)
        incorporadas: set[int] = set()

        declaradas: set[int] = set()
        for campo, valor in campos:
            if not (campo.startswith("estado") or "enmienda" in campo):
                continue
            texto = sin_acentos(f"{campo} {valor}").lower()
            # Declarar que algo NO esta incorporado tambien es declararlo: sin
            # eso, una cita a trabajo futuro se ve igual que un asiento olvidado.
            if any(t in texto for t in ("diferid", "pendiente", "no incorporad")):
                declaradas |= {int(n) for n in RE_ENMIENDA_TEXTO.findall(valor)}
                continue
            if "incorporad" not in texto:
                continue
            if "enmienda" in campo:
                # Un renglón del catálogo enumera con `·` y cada segmento
                # PERTENECE a la enmienda que lo encabeza; las demás que cite
                # son contexto («36 … revierte lo que la enmienda_35 asentó»)
                # y atribuírselas al spec sería inventar una incorporación.
                if campo.startswith("enmiendas incorporadas"):
                    # Las cabeceras actuales usan la forma compacta `01, 05`.
                    # Sólo se acepta una lista completa de folios para no
                    # confundir números de sección o fechas con identidades.
                    if re.fullmatch(r"\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*", valor):
                        incorporadas |= {
                            int(n) for n in re.findall(r"\d{1,3}", valor)
                        }
                    else:
                        for segmento in valor.split("·"):
                            numero = encabeza_segmento(segmento)
                            if numero is not None:
                                incorporadas.add(numero)
                else:
                    for segmento in valor.split("·"):
                        numero = encabeza_segmento(segmento)
                        if numero is not None:
                            incorporadas.add(numero)
            else:
                # El `Estado` enumera en corto («con las enmiendas 77 y 79
                # incorporadas»): ahí cuentan todas.
                incorporadas |= {int(n) for n in RE_ENMIENDA_TEXTO.findall(valor)}

        fichas[ruta.stem] = {
            "archivo": ruta.name,
            "enlace": os.path.relpath(ruta, raiz / "sdd"),
            "titulo": titulo,
            "estado": primer_valor(campos, "estado"),
            "incorporadas": incorporadas,
            "declaradas": declaradas,
            "cuerpo": cuerpo_sin_cabecera(ruta),
            "campos": campos,
            "secciones": indice_de_secciones(ruta.read_text(encoding="utf-8")),
        }
    return fichas


RE_SPEC_ENLAZADO = re.compile(r"\]\([^)]*?(spec_[a-z0-9-]+)\.md")


def carga_modulos(raiz: Path) -> dict[str, list[str]]:
    """spec → módulos SDD, declarado desde el estado de cada módulo."""
    mapa: dict[str, set[str]] = {}

    def recoge(ruta: Path, seccion: str, etiqueta: str) -> None:
        if not ruta.exists():
            return
        dentro = False
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.startswith("## "):
                dentro = seccion in sin_acentos(linea).lower()
                continue
            if dentro:
                for spec in RE_SPEC_ENLAZADO.findall(linea):
                    mapa.setdefault(spec, set()).add(etiqueta)

    raices = (raiz / "sesiones/modulos", raiz / "gobernanza/sesiones/modulos")
    for estado in sorted(path for root in raices for path in root.glob("*/estado.md")):
        slug = estado.parent.name
        recoge(estado, "specs y dependencias de modulo", slug)
    return {spec: sorted(slugs) for spec, slugs in mapa.items()}


# ── contraste de los dos lados ────────────────────────────────────────────────

def revisa_secciones(enmiendas, specs) -> list[str]:
    """Contrasta cada § citada contra las que el spec destino tiene de verdad.

    Dentro de un renglón, una § pertenece al último `spec_X.md` nombrado antes
    de ella; si no hay ninguno, al propio documento cuando es un spec. Informa y
    no bloquea: una cita rota es un dedo mal apuntado, no una contradicción.
    """
    fallos: list[str] = []

    def revisa(texto: str, propio: str | None, origen: str) -> None:
        destino = propio
        # Una § pertenece al ultimo documento nombrado antes de ella, y ese
        # documento puede ser una ENMIENDA: «(enmienda_51 §3.4)» no habla de las
        # secciones del spec que la cita. De esas no se indexan secciones, asi
        # que la referencia se deja pasar en vez de inventarle un dueno.
        patron = re.compile(
            r"(spec_[a-z0-9-]+)\.md|(enmienda[_ ]\d{1,3})|" + RE_REFERENCIA.pattern
        )
        for m in patron.finditer(texto):
            if m.group(1):
                destino = m.group(1)
                continue
            if m.group(2):
                destino = None
                continue
            spec = specs.get(destino)
            if not spec:
                continue
            ref = normaliza_seccion(m.group(3))
            if ref and ref not in spec["secciones"]:
                fallos.append(
                    f"{origen} cita `{destino}.md` §{ref}, que ese spec no tiene "
                    f"—ni como encabezado ni como punto numerado—."
                )

    for nombre, spec in specs.items():
        for campo, valor in spec["campos"]:
            revisa(valor, nombre, f"La cabecera de `{spec['archivo']}`")
        for bloque in re.findall(r"> \*\*Orden de lectura\.\*\*.*?(?:\n\n|\Z)",
                                 spec["cuerpo"], re.S):
            revisa(bloque, nombre, f"El orden de lectura de `{spec['archivo']}`")

    for ficha in enmiendas.values():
        for campo, valor in ficha["campos"]:
            if campo.startswith(CAMPOS_DESTINO) or campo.startswith(CAMPOS_SECUNDARIOS):
                revisa(valor, None, f"`{ficha['archivo']}`")

    return sorted(set(fallos))


def contrasta(enmiendas, specs, modulos) -> dict[str, list[str]]:
    contradicciones: list[str] = []
    cabeceras: list[str] = []
    cobertura: list[str] = []

    por_numero: dict[int, list[dict]] = {}
    for ficha in enmiendas.values():
        if ficha["numero"] is not None:
            por_numero.setdefault(ficha["numero"], []).append(ficha)

    for numero, fichas in sorted(por_numero.items()):
        if len(fichas) > 1 and not all(f["colision_declarada"] for f in fichas):
            nombres = " · ".join(f"`{f['archivo']}`" for f in fichas)
            contradicciones.append(
                f"**Número {numero:02d} duplicado** — {nombres}. Ninguna lo "
                f"declara en su cabecera."
            )

    reclamada_por: dict[int, list[str]] = {}
    for nombre, spec in specs.items():
        for numero in spec["incorporadas"]:
            reclamada_por.setdefault(numero, []).append(nombre)

    for numero, fichas in sorted(por_numero.items()):
        for ficha in fichas:
            reclamada = reclamada_por.get(numero, [])
            destinos = ficha["specs"] + ficha["toca"]

            if ficha["estado"] == "Incorporada" and not reclamada and not destinos:
                cabeceras.append(
                    f"`{ficha['archivo']}` se declara **incorporada**, pero no "
                    f"dice a qué spec ni ninguno la reclama."
                )
            if ficha["estado"] not in {"Incorporada", "Validada"} and reclamada:
                contradicciones.append(
                    f"`{ficha['archivo']}` figura como incorporada en "
                    f"{' · '.join('`' + s + '.md`' for s in reclamada)}, pero su "
                    f"propio Estado dice «{ficha['estado']}»."
                )
            # Con un folio compartido (la colisión declarada del 14), el
            # destino que vale es el de CUALQUIERA de las que lo llevan: por
            # número solo no se distingue a cuál se refiere el spec.
            destinos_del_folio = {
                s for hermana in fichas for s in hermana["specs"] + hermana["toca"]
            }
            for nombre in reclamada:
                if destinos_del_folio and nombre not in destinos_del_folio:
                    contradicciones.append(
                        f"`{nombre}.md` incorpora la enmienda {numero:02d}, que "
                        f"declara como destino "
                        f"{' · '.join('`' + s + '.md`' for s in destinos)}."
                    )
            # El asiento se debe en cada destino PRINCIPAL. `Toca` es roce
            # incidental —el spec se menciona, no se enmienda— y exigirle
            # asiento llenaría de renglones cabeceras que nadie tocó.
            if ficha["estado"] == "Incorporada" or reclamada:
                huecos = [
                    d for d in ficha["specs"]
                    if d in specs and d not in reclamada
                ]
                if huecos:
                    cabeceras.append(
                        f"`{ficha['archivo']}` está incorporada, pero no la "
                        f"registra la cabecera de "
                        f"{' · '.join('`' + d + '.md`' for d in huecos)}."
                    )

            if not destinos:
                cabeceras.append(
                    f"`{ficha['archivo']}` no declara spec destino: no se sabe "
                    f"qué contrato modifica."
                )
            elif ficha["destino_inferido"]:
                cabeceras.append(
                    f"`{ficha['archivo']}` no declara spec destino en un campo; "
                    f"se infirió {' · '.join('`' + s + '.md`' for s in destinos)} "
                    f"leyendo su preámbulo."
                )
            if not ficha["declara_estado"]:
                cabeceras.append(
                    f"`{ficha['archivo']}` no declara `Estado` en su cabecera."
                )
            for spec in destinos:
                if spec not in specs:
                    cabeceras.append(
                        f"`{ficha['archivo']}` apunta a `{spec}.md`, que no "
                        f"existe en `sdd/`."
                    )

    for numero, nombres in sorted(reclamada_por.items()):
        if numero not in por_numero:
            cabeceras.append(
                f"{' · '.join('`' + s + '.md`' for s in nombres)} declara "
                f"incorporada la enmienda {numero:02d}, que no tiene archivo en "
                f"`sdd/`."
            )

    # Una enmienda que ninguna cabecera reclama, pero que el cuerpo del spec ya
    # usa, es el punto ciego que queda cuando los dos lados callan: figuraria
    # como viva para siempre.
    sospechas: list[str] = []
    for numero, fichas in sorted(por_numero.items()):
        for ficha in fichas:
            if ficha["estado"] == "Incorporada" or numero in reclamada_por:
                continue
            for destino in ficha["specs"]:
                spec = specs.get(destino)
                if not spec or numero in spec["declaradas"]:
                    continue
                citas = list(RE_ENMIENDA_TEXTO.finditer(spec["cuerpo"]))
                citas = [m for m in citas if int(m.group(1)) == numero]
                if not citas:
                    continue
                declara = any(
                    "incorporad" in sin_acentos(
                        spec["cuerpo"][m.start(): m.start() + 160]
                    ).lower()
                    for m in citas
                )
                if declara:
                    contradicciones.append(
                        f"`{destino}.md` **declara en su cuerpo** incorporada la "
                        f"enmienda {numero:02d}, pero no la registra en su "
                        f"cabecera y la enmienda tampoco lo dice."
                    )
                else:
                    sospechas.append(
                        f"`{destino}.md` usa la enmienda {numero:02d} en su "
                        f"cuerpo ({len(citas)} cita(s)) y ninguna cabecera la da "
                        f"por incorporada: o ya lo está sin asentarse, o la cita "
                        f"es una referencia a trabajo pendiente."
                    )

    for spec in sorted(modulos):
        if spec not in specs:
            cobertura.append(
                f"`sesiones/modulos/` cita `{spec}.md`, que no existe en "
                f"`sdd/`."
            )
    for nombre in sorted(specs):
        module = primer_valor(specs[nombre]["campos"], "modulo")
        module = module.strip().strip("`")
        if module not in modulos.get(nombre, []):
            cobertura.append(
                f"`{nombre}.md` no lo declara su módulo dueño "
                f"`{module or 'sin Módulo'}` en «Specs y dependencias de módulo»."
            )

    return {
        "Contradicciones": contradicciones,
        "Cabeceras incompletas": cabeceras,
        "Posible incorporación sin registrar": sospechas,
        "Secciones citadas": revisa_secciones(enmiendas, specs),
        "Cobertura por módulo": cobertura,
    }


# ── redacción del índice ──────────────────────────────────────────────────────

RE_PREFIJO_TITULO = re.compile(r"^Enmienda\s+\d{1,3}\s*[:—–-]\s*", re.IGNORECASE)
RE_TOKEN_ESTADO = re.compile(
    r"\b(Validad[oa]|Propuest[oa]|Borrador|Diferida|Inconsistente)\b"
)
RE_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


def titulo_corto(titulo: str) -> str:
    """«Enmienda 74: el asidero…» → «el asidero…»; el número ya es la columna."""
    return RE_PREFIJO_TITULO.sub("", titulo).strip() or titulo


def token_estado(texto: str) -> str:
    """El estado es un token, no el párrafo de aprobación que lo acompaña."""
    m = RE_TOKEN_ESTADO.search(texto)
    if not m:
        return "—"
    fecha = RE_FECHA.search(texto)
    return f"{m.group(1)} ({fecha.group(0)})" if fecha else m.group(1)


def escapa(texto: str) -> str:
    return texto.replace("|", "\\|")


def enlace(ficha: dict) -> str:
    numero = f"{ficha['numero']:02d}" if ficha["numero"] is not None else "—"
    return f"[{numero}]({ficha['enlace']})"


def redacta(raiz: Path, enmiendas, specs, modulos, grupos) -> str:
    reclamadas = {n for spec in specs.values() for n in spec["incorporadas"]}
    vivas, incorporadas = [], []
    for ficha in sorted(
        enmiendas.values(), key=lambda f: (f["numero"] or 0, f["archivo"])
    ):
        dentro = ficha["estado"] == "Incorporada" or ficha["numero"] in reclamadas
        (incorporadas if dentro else vivas).append(ficha)

    total_fallos = sum(len(v) for v in grupos.values())
    l: list[str] = []

    l.append("# Índice de `sdd/`")
    l.append("")
    l.append(
        "> **Generado.** Lo escribe `herramientas/indice.py` leyendo las "
        "cabeceras de los specs, las de las enmiendas y la sección «Specs y "
        "dependencias de módulo» de cada `sesiones/modulos/<slug>/estado.md`. "
        "**No se edita "
        "a mano**: lo que aquí falte o sobre se corrige en la cabecera de origen "
        "y se regenera."
    )
    l.append(">")
    l.append(
        f"> {len(specs)} specs · {len(enmiendas)} enmiendas "
        f"({len(vivas)} vivas, {len(incorporadas)} incorporadas) · "
        f"{total_fallos} señalamiento(s)."
    )
    l.append("")
    l.append("---")
    l.append("")

    l.append("## 1. Enmiendas vivas")
    l.append("")
    l.append(
        "Todavía no viven dentro de su spec. Ésta es la superficie de trabajo: "
        "aquí manda la enmienda, no el spec."
    )
    l.append("")
    if vivas:
        l.append("| # | Enmienda | Estado | Specs que modifica |")
        l.append("|---|---|---|---|")
        for f in vivas:
            destinos = " · ".join(f"`{s}`" for s in f["specs"] + f["toca"])
            l.append(
                f"| {enlace(f)} | {escapa(titulo_corto(f['titulo']))} | "
                f"{f['estado']} | {destinos or '**—**'} |"
            )
    else:
        l.append("Ninguna: todas las enmiendas viven ya dentro de su spec.")
    l.append("")

    l.append("## 2. Por spec")
    l.append("")
    l.append(
        "Una enmienda que toca dos specs aparece bajo los dos, sin duplicar "
        "archivo. Un spec transversal puede pertenecer a varios módulos."
    )
    l.append("")
    for nombre in sorted(specs):
        spec = specs[nombre]
        owners = modulos.get(nombre, [])
        propias = [f for f in vivas if nombre in f["specs"] + f["toca"]]
        dentro = sorted(spec["incorporadas"])
        l.append(f"### [`{spec['archivo']}`]({spec['enlace']})")
        l.append("")
        l.append(f"- **Estado:** {token_estado(spec['estado'])}")
        l.append(
            "- **Módulos:** "
            + (" · ".join(f"`{slug}`" for slug in owners) if owners else "**ninguno declarado**")
        )
        l.append(
            "- **Vivas:** "
            + (" · ".join(enlace(f) for f in propias) if propias else "—")
        )
        if dentro:
            l.append(
                f"- **Incorporadas ({len(dentro)}):** "
                + ", ".join(f"{n:02d}" for n in dentro)
            )
        l.append("")

    l.append("## 3. Señalamientos")
    l.append("")
    if not total_fallos:
        l.append("Ninguno: los dos lados de cada relación coinciden.")
    else:
        l.append(
            "No se resuelven por fecha, folio ni intuición: se corrigen en la "
            "cabecera de origen. Una **contradicción** es que los dos lados "
            "digan cosas distintas; una **cabecera incompleta** es que un lado "
            "no diga nada."
        )
        l.append("")
        for titulo, fallos in grupos.items():
            if not fallos:
                continue
            l.append(f"### {titulo} ({len(fallos)})")
            l.append("")
            for fallo in fallos:
                l.append(f"- {fallo}")
            l.append("")
    l.append("")

    insumos = sorted(
        p.name for p in (raiz / "sdd").iterdir()
        if p.is_file()
        and p.name != "INDICE.md"
        and not p.name.startswith(PREFIJOS_CONOCIDOS)
    )
    l.append("## 4. Insumos")
    l.append("")
    l.append(
        "Ni contrato ni corrección: dictámenes, dictados, análisis, propuestas "
        "y sondas que sirvieron de evidencia. No gobiernan."
    )
    l.append("")
    for nombre in insumos:
        l.append(f"- [`{nombre}`]({nombre})")
    l.append("")

    # El archivo histórico va al final: es lo más largo y lo menos accionable.
    l.append("## 5. Enmiendas incorporadas")
    l.append("")
    l.append(
        "Ya viven dentro de su spec. **Manda el spec, no la enmienda**; se "
        "conservan por trazabilidad."
    )
    l.append("")
    l.append("| # | Enmienda | Specs |")
    l.append("|---|---|---|")
    for f in incorporadas:
        destinos = " · ".join(f"`{s}`" for s in f["specs"] + f["toca"])
        l.append(
            f"| {enlace(f)} | {escapa(titulo_corto(f['titulo']))} | "
            f"{destinos or '—'} |"
        )
    l.append("")

    return "\n".join(l)
