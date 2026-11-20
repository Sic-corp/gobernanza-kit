"""Carga segura y análisis estático, compartidos por F-0101 y F-0102."""

import ast
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tokenize

from .modelo import Documento, coincide, diagnostico, referencia


def json_estricto(texto):
    def objeto(pares):
        salida = {}
        for clave, valor in pares:
            if clave in salida:
                raise ValueError(f"Clave JSON duplicada: {clave}")
            salida[clave] = valor
        return salida

    def constante(valor):
        raise ValueError(f"Constante JSON inválida: {valor}")

    return json.loads(texto, object_pairs_hook=objeto, parse_constant=constante)


def entero(valor):
    return type(valor) is int and valor > 0


class Repositorio:
    """Instantánea en memoria. No importa módulos ni ejecuta procesos."""

    def __init__(self, raiz):
        self.raiz = Path(raiz).resolve()
        self.config = {}
        self.documentos = []
        self.por_id = {}
        self.por_ref = {}
        self.errores = []
        self.pendientes = []
        self.pruebas = []
        self.externas = {}

    def error(self, codigo, ruta, mensaje, requisito="Formato núcleo esquema 1",
              resolucion="Corrige el documento o su declaración antes de continuar."):
        self.errores.append(diagnostico(codigo, ruta, requisito, mensaje, resolucion))

    def segura(self, ruta, origen=None):
        """Comprueba destino efectivo antes de cualquier apertura de contenido."""
        origen = origen or (ruta if isinstance(ruta, str) and ruta else ".")
        if (not isinstance(ruta, str) or not ruta or "\\" in ruta
                or PurePosixPath(ruta).is_absolute() or ".." in PurePosixPath(ruta).parts):
            self.error("RUTA_INVALIDA", origen, f"Ruta relativa inválida: {ruta!r}")
            return None
        try:
            destino = self.raiz / ruta
            if not destino.resolve().is_relative_to(self.raiz):
                self.error("RUTA_EXTERNA", ruta, f"El destino efectivo de {ruta} declarado en {origen} sale de la raíz.",
                           "Lecturas dentro de la raíz declarada", "Elimina el escape o declara el objeto dentro del proyecto.")
                return None
            return destino
        except (OSError, RuntimeError, ValueError) as exc:
            self.error("RUTA_INVALIDA", origen, str(exc))
            return None

    def leer(self, ruta):
        destino = self.segura(ruta)
        if destino is None:
            return None
        try:
            return destino.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.error("LECTURA", ruta, str(exc), "Archivo UTF-8 legible",
                       "Restaura el archivo y comprueba sus permisos y codificación.")
            return None

    def rutas(self, patrones):
        """Enumera solo los subárboles declarados y nunca atraviesa un escape."""
        encontrados = set()
        for patron in patrones:
            if self.segura(patron) is None:
                continue
            partes = PurePosixPath(patron).parts
            fijas = []
            for parte in partes:
                if any(c in parte for c in "*?["):
                    break
                fijas.append(parte)
            base = self.raiz.joinpath(*fijas)
            if base.is_file():
                relativa = base.relative_to(self.raiz).as_posix()
                if coincide(relativa, patron) and self.segura(relativa) is not None:
                    encontrados.add(relativa)
                continue
            if not base.exists():
                continue
            def error_recorrido(exc):
                self.error("LECTURA", str(exc.filename or base), str(exc),
                           "Inventario legible", "Comprueba los permisos del directorio declarado.")

            for directorio, carpetas, archivos in os.walk(base, followlinks=False, onerror=error_recorrido):
                conservar = []
                for nombre in sorted(carpetas):
                    if nombre in {".git", "__pycache__"}:
                        continue
                    p = Path(directorio) / nombre
                    relativa = p.relative_to(self.raiz).as_posix()
                    if self.segura(relativa) is None:
                        continue
                    if p.is_symlink():
                        self.error("DIRECTORIO_ENLAZADO", relativa,
                                   "No se recorren directorios enlazados en el inventario estático.",
                                   resolucion="Declara la ruta real interna, sin enlaces de directorio.")
                        continue
                    conservar.append(nombre)
                carpetas[:] = conservar
                for nombre in sorted(archivos):
                    relativa = (Path(directorio) / nombre).relative_to(self.raiz).as_posix()
                    if coincide(relativa, patron) and self.segura(relativa) is not None:
                        encontrados.add(relativa)
        return sorted(r for r in encontrados if r.split("/", 1)[0].casefold() != "playground")

    def cargar_config(self):
        ruta = "gobernanza/config.json"
        texto = self.leer(ruta)
        if texto is None:
            return False
        try:
            datos = json_estricto(texto)
        except ValueError as exc:
            self.error("JSON_INVALIDO", ruta, str(exc))
            return False
        if not isinstance(datos, dict):
            self.error("CONFIG_INVALIDA", ruta, "La configuración debe ser un objeto JSON.")
            return False
        if type(datos.get("schema")) is not int or datos["schema"] != 1:
            self.error("ESQUEMA", ruta, "Se requiere schema entero 1.")
        if not isinstance(datos.get("proyecto"), str) or not datos["proyecto"]:
            self.error("PROYECTO", ruta, "Falta una identidad de proyecto.")
        documentos = datos.get("documentos", ["sdd/spec_*.md", "sdd/funcionalidades/*.md",
                                              "sesiones/historial/*.md", "gobernanza/sesiones/historial/*.md"])
        if not isinstance(documentos, list) or not documentos:
            self.error("DOCUMENTOS", ruta, "documentos debe ser una lista de patrones.")
        else:
            for patron in documentos:
                self.segura(patron, ruta)
        raices = datos.get("raices")
        if not isinstance(raices, dict):
            self.error("RAICES", ruta, "raices debe ser un objeto de listas.")
        else:
            for nombre in ("solucion", "pruebas", "controles"):
                if not isinstance(raices.get(nombre), list):
                    self.error("RAICES", ruta, f"raices.{nombre} debe ser una lista.")
                    continue
                for declaracion in raices[nombre]:
                    self.segura(declaracion, ruta)
        verificadores = datos.get("verificadores")
        vistos = set()
        if not isinstance(verificadores, list):
            self.error("VERIFICADORES", ruta, "verificadores debe ser una lista.")
        else:
            for verificador in verificadores:
                if not isinstance(verificador, dict):
                    self.error("VERIFICADOR", ruta, "Cada verificador debe ser un objeto.")
                    continue
                identidad = verificador.get("id")
                if not isinstance(identidad, str) or not identidad or identidad in vistos:
                    self.error("VERIFICADOR", ruta, "ID de verificador ausente o duplicado.")
                else:
                    vistos.add(identidad)
                if not isinstance(verificador.get("runner"), str) or not verificador["runner"]:
                    self.error("VERIFICADOR", ruta, "Falta el runner declarado.")
                args = verificador.get("args")
                if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
                    self.error("VERIFICADOR", ruta, "args debe ser una lista no vacía de cadenas.")
                self.segura(verificador.get("cwd", "."), ruta)
                salidas = verificador.get("salidas_permitidas", [])
                if not isinstance(salidas, list):
                    self.error("VERIFICADOR", ruta, "salidas_permitidas debe ser una lista.")
                else:
                    for salida in salidas:
                        self.segura(salida, ruta)
        externas = datos.get("referencias_externas", {})
        if not isinstance(externas, dict):
            self.error("EXTERNAS", ruta, "referencias_externas debe ser un mapa.")
        else:
            for ref, procedencia in externas.items():
                if (referencia(ref) is None or not isinstance(procedencia, dict)
                        or any(not isinstance(procedencia.get(c), str) or not procedencia[c]
                               for c in ("proyecto", "evidencia"))):
                    self.error("EXTERNA_INVALIDA", ruta, f"Procedencia externa inválida: {ref}")
                else:
                    self.externas[ref] = procedencia
        self.config = dict(datos, documentos=documentos)
        return not self.errores

    def cargar_documento(self, ruta):
        texto = self.leer(ruta)
        if texto is None:
            return
        try:
            lineas = texto.splitlines()
            if not lineas or lineas[0] != "---":
                raise ValueError("Falta delimitador inicial ---.")
            fin = lineas.index("---", 1)
            datos = json_estricto("\n".join(lineas[1:fin]))
            if not isinstance(datos, dict):
                raise ValueError("El frontmatter debe ser un objeto JSON.")
        except ValueError as exc:
            self.error("FRONTMATTER", ruta, str(exc))
            return
        inicio = len(self.errores)
        if type(datos.get("schema")) is not int or datos["schema"] != 1:
            self.error("ESQUEMA", ruta, "Se requiere schema entero 1.")
        identidad = datos.get("id")
        ident = referencia(identidad)
        if ident is None or ident[1] is not None:
            self.error("IDENTIDAD", ruta, "Identidad permanente ausente o inválida.")
            return
        for campo in ("dependencias", "dependencias_propuestas", "funcionalidades",
                      "funcionalidades_propuestas", "sesiones"):
            if campo in datos and not isinstance(datos[campo], list):
                self.error("CAMPO_INVALIDO", ruta, f"{campo} debe ser lista.")
            elif campo in {"funcionalidades", "funcionalidades_propuestas", "sesiones"}:
                for valor in datos.get(campo, []):
                    ref = valor.get("ref") if isinstance(valor, dict) else valor
                    partes = referencia(ref)
                    prefijos = ("F-",) if campo.startswith("funcionalidades") else ("S", "G")
                    if partes is None or not partes[0].startswith(prefijos):
                        self.error("TIPO_REFERENCIA", ruta, f"{campo} contiene una referencia de tipo incorrecto: {ref!r}.")
        if identidad.startswith("F-"):
            revisiones = datos.get("revisiones")
            actual = datos.get("revision_actual")
            if (not isinstance(revisiones, list) or not revisiones
                    or not all(entero(n) for n in revisiones)
                    or revisiones != list(range(1, len(revisiones) + 1))
                    or not entero(actual) or actual not in revisiones):
                self.error("REVISIONES", ruta, "Revisiones deben ser enteros consecutivos desde 1 y contener revision_actual.")
            criterios = datos.get("criterios")
            if not isinstance(criterios, dict):
                self.error("CRITERIOS", ruta, "criterios debe mapear revisión a lista de IDs.")
            else:
                for revision, ids in criterios.items():
                    if (not isinstance(revisiones, list) or revision not in [str(n) for n in revisiones]
                            or not isinstance(ids, list) or not ids
                            or not all(isinstance(c, str) and re.fullmatch(r"C\d{2,}", c) for c in ids)
                            or len(ids) != len(set(c for c in ids if isinstance(c, str)))):
                        self.error("CRITERIOS", ruta, f"IDs de criterio inválidos para revisión {revision}.")
                if isinstance(revisiones, list) and any(str(n) not in criterios for n in revisiones):
                    self.error("CRITERIOS", ruta, "Cada revisión debe declarar criterios.")
            if not isinstance(datos.get("modulo"), str) or not datos["modulo"].startswith("M-"):
                self.error("MODULO", ruta, "La funcionalidad requiere módulo dueño.")
        if identidad.startswith("M-") and not entero(datos.get("version")):
            self.error("VERSION", ruta, "El spec requiere versión entera positiva.")
        objetos = datos.get("objetos", [])
        if not isinstance(objetos, list):
            self.error("OBJETOS", ruta, "objetos debe ser una lista de rutas.")
        else:
            for objeto in objetos:
                if self.segura(objeto, ruta) is not None:
                    self.rutas([objeto])  # Comprueba también destinos efectivos bajo patrones.
        compartidos = datos.get("objetos_compartidos", [])
        if "objetos_compartidos" in datos and not identidad.startswith("M-"):
            self.error("PROPIETARIO_COMPARTIDO", ruta, "Solo un spec de módulo declara propiedad compartida.")
        if not isinstance(compartidos, list):
            self.error("OBJETOS", ruta, "objetos_compartidos debe ser una lista.")
        else:
            for objeto in compartidos:
                if not isinstance(objeto, dict) or not isinstance(objeto.get("consumidores"), list):
                    self.error("OBJETOS", ruta, "Objeto compartido requiere ruta y consumidores.")
                else:
                    if self.segura(objeto.get("ruta"), ruta) is not None:
                        self.rutas([objeto["ruta"]])
                    for consumidor in objeto["consumidores"]:
                        partes = referencia(consumidor)
                        if partes is None or not partes[0].startswith("F-"):
                            self.error("TIPO_REFERENCIA", ruta, "El consumidor compartido debe ser una funcionalidad.")
        if len(self.errores) == inicio:
            doc = Documento(ruta, datos, "\n".join(lineas[fin + 1:]))
            self.documentos.append(doc)
            self.por_id.setdefault(identidad, []).append(doc)

    def relaciones(self, doc):
        for campo in ("modulo", "dependencias", "dependencias_propuestas", "funcionalidades",
                      "funcionalidades_propuestas", "sesiones"):
            valores = doc.datos.get(campo, [])
            valores = [valores] if campo == "modulo" and valores else valores
            for valor in valores:
                propuesta = campo.endswith("_propuestas")
                if isinstance(valor, dict):
                    propuesta = propuesta or valor.get("estado") == "propuesta"
                    valor = valor.get("ref")
                yield valor, propuesta, campo
        for objeto in doc.datos.get("objetos_compartidos", []):
            for consumidor in objeto["consumidores"]:
                yield consumidor, False, "consumidores"

    def resolver(self, ref, origen, propuesta=False):
        partes = referencia(ref)
        if partes is None:
            self.error("REFERENCIA_INVALIDA", origen, f"Referencia malformada: {ref!r}")
            return None
        identidad, revision = partes
        if ref in self.externas:
            return None
        candidatos = self.por_id.get(identidad, [])
        if not candidatos:
            if propuesta:
                self.pendiente(ref, origen)
            else:
                self.error("REFERENCIA_AUSENTE", origen, f"No existe contrato para {ref}.")
            return None
        if len(candidatos) != 1:
            self.error("REFERENCIA_AMBIGUA", origen, f"Más de un documento define {ref}.")
            return None
        doc = candidatos[0]
        if doc.tipo == "funcionalidad":
            revisiones = doc.datos["revisiones"]
            if revision is None:
                if len(revisiones) != 1:
                    self.error("REVISION_AMBIGUA", origen, f"{ref} requiere revisión explícita.")
                    return None
                revision = revisiones[0]
            if revision not in revisiones:
                if propuesta:
                    self.pendiente(ref, origen)
                else:
                    self.error("REVISION_AUSENTE", origen, f"No existe {ref}.")
                return None
            doc = self.por_ref.get(f"{identidad}@r{revision}", doc)
        elif doc.tipo == "modulo" and revision is not None and revision != doc.datos["version"]:
            if propuesta:
                self.pendiente(ref, origen)
            else:
                self.error("VERSION_AUSENTE", origen, f"No existe {ref}.")
            return None
        return doc, revision

    def pendiente(self, ref, origen):
        self.pendientes.append(diagnostico("REFERENCIA_PROPUESTA", origen,
            "Propuesta todavía no materializada", f"Referencia pendiente: {ref}",
            "Concilia la propuesta antes de promoverla a contrato exigible."))

    def inventariar_pruebas(self):
        verificadores = {v["id"] for v in self.config["verificadores"]}
        ids, selectores = set(), set()
        archivos_vistos = set()
        for base in self.config["raices"]["pruebas"]:
            # Una raíz de pruebas representa un directorio; también admite archivo explícito.
            patron = base if base.endswith(".py") else base.rstrip("/") + "/**/*.py"
            for ruta in self.rutas([patron]):
                if ruta in archivos_vistos:
                    continue
                archivos_vistos.add(ruta)
                texto = self.leer(ruta)
                if texto is None:
                    continue
                try:
                    arbol = ast.parse(texto, filename=ruta)
                    comentarios = {t.start[0]: t for t in tokenize.generate_tokens(io.StringIO(texto).readline)
                                   if t.type == tokenize.COMMENT and t.string.startswith("# gobernanza-test:")}
                except (SyntaxError, ValueError, tokenize.TokenError) as exc:
                    self.error("PYTHON_INVALIDO", ruta, str(exc))
                    continue
                usados = set()
                clases = set()
                bases_unittest = {"unittest.TestCase", "TestCase"}
                for nodo in arbol.body:
                    if isinstance(nodo, ast.Import):
                        bases_unittest.update((a.asname or a.name) + ".TestCase"
                                              for a in nodo.names if a.name == "unittest")
                    elif isinstance(nodo, ast.ImportFrom) and nodo.module == "unittest":
                        bases_unittest.update(a.asname or a.name for a in nodo.names if a.name == "TestCase")
                for nodo in arbol.body:
                    if isinstance(nodo, ast.ClassDef):
                        nombres = [ast.unparse(b) for b in nodo.bases]
                        if any(b in bases_unittest or b in clases for b in nombres):
                            clases.add(nodo.name)
                for clase in arbol.body:
                    if not isinstance(clase, ast.ClassDef) or clase.name not in clases:
                        continue
                    for metodo in clase.body:
                        if not isinstance(metodo, (ast.FunctionDef, ast.AsyncFunctionDef)) or not metodo.name.startswith("test_"):
                            continue
                        inicio = min([metodo.lineno] + [d.lineno for d in metodo.decorator_list])
                        token = comentarios.get(inicio - 1)
                        if token is None or token.start[1] != metodo.col_offset:
                            self.error("PRUEBA_SIN_VINCULO", ruta, f"{clase.name}.{metodo.name} requiere comentario adyacente antes del método/decorador.")
                            continue
                        usados.add(token.start[0])
                        try:
                            datos = json_estricto(token.string.split(":", 1)[1])
                            if not isinstance(datos, dict) or any(not isinstance(datos.get(k), str) or not datos[k]
                                                                 for k in ("id", "criterio", "verificador", "selector")):
                                raise ValueError("Se requieren id, criterio, verificador y selector como cadenas.")
                        except ValueError as exc:
                            self.error("VINCULO_INVALIDO", ruta, str(exc))
                            continue
                        relativo = PurePosixPath(ruta).relative_to(PurePosixPath(base).parent if base.endswith(".py") else PurePosixPath(base))
                        modulo = ".".join(relativo.with_suffix("").parts)
                        esperado = f"{modulo}.{clase.name}.{metodo.name}"
                        if datos["selector"] != esperado:
                            self.error("SELECTOR", ruta, f"Selector declarado {datos['selector']} no corresponde a {esperado}.")
                        if datos["id"] in ids or datos["selector"] in selectores:
                            self.error("PRUEBA_DUPLICADA", ruta, f"ID o selector duplicado: {datos['id']}.")
                        ids.add(datos["id"])
                        selectores.add(datos["selector"])
                        if datos["verificador"] not in verificadores:
                            self.error("VERIFICADOR_AUSENTE", ruta, f"No existe verificador {datos['verificador']}.")
                        match = re.fullmatch(r"(F-\d{4}@r[1-9]\d*)/(C\d{2,})", datos["criterio"])
                        if match is None:
                            self.error("CRITERIO", ruta, f"Criterio inválido: {datos['criterio']}.")
                        else:
                            resuelto = self.resolver(match[1], ruta)
                            if resuelto is None or datos["criterio"] not in {c["referencia"] for c in resuelto[0].criterios(resuelto[1])}:
                                self.error("CRITERIO_AUSENTE", ruta, f"No existe criterio local {datos['criterio']}.")
                        self.pruebas.append(dict(datos, ruta=ruta, linea=token.start[0], descubierto=False))
                for linea in comentarios.keys() - usados:
                    self.error("VINCULO_HUERFANO", ruta, f"Comentario de línea {linea} no está junto a un caso unittest soportado.")

    def cargar(self):
        if not self.cargar_config():
            return self
        for ruta in self.rutas(self.config["documentos"]):
            if not ruta.startswith(("sdd/registro/", "sdd/operaciones/")):
                self.cargar_documento(ruta)
        if (self.raiz / "sdd/registro").exists():
            from .flujo_sdd import integrar_documentos
            integrar_documentos(self)
        if not self.documentos and not self.errores:
            self.error("SIN_DOCUMENTOS", "gobernanza/config.json", "No se encontró ningún contrato.")
        for identidad, documentos in self.por_id.items():
            if len(documentos) > 1:
                for doc in documentos:
                    self.error("IDENTIDAD_DUPLICADA", doc.ruta, f"Identidad duplicada: {identidad}.")
        for ref in self.externas:
            if referencia(ref)[0] in self.por_id:
                self.error("COLISION_EXTERNA", "gobernanza/config.json", f"{ref} también tiene identidad local.")
        for doc in self.documentos:
            for ref, propuesta, _ in self.relaciones(doc):
                self.resolver(ref, doc.ruta, propuesta)
        self.inventariar_pruebas()
        return self


def cargar(raiz):
    return Repositorio(raiz).cargar()


def _externas_nativas(repo, plan):
    from .convivencia import ErrorConvivencia, FICHA, OID, RAICES, RAMA, frontal, huella_datos

    candidatas = [ruta for ruta in repo.listar("gobernanza/compatibilidad/heimdall/")
                  if re.fullmatch(rf"gobernanza/compatibilidad/heimdall/{plan['folio']}(?:_[^/]+)?\.md", ruta)]
    declaradas = repo.config.get("referencias_externas", {})
    if not isinstance(declaradas, dict):
        raise ErrorConvivencia("El registro de procedencias debe ser un objeto.")
    if not candidatas:
        if declaradas and plan["folio"] == "G01-22":
            raise ErrorConvivencia("Falta el puente G del folio.", plan["ruta"])
        return []
    if len(candidatas) != 1 or plan["dominio"] != "G":
        raise ErrorConvivencia("Puente de lectura múltiple o en dominio incorrecto.", plan["ruta"])
    puente = candidatas[0]
    datos, _ = frontal(repo.texto(puente), puente)
    dependencias = datos.get("dependencias")
    if (type(datos.get("schema")) is not int or datos["schema"] != 1 or datos.get("id") != plan["folio"]
            or not isinstance(dependencias, list) or any(not isinstance(ref, str) for ref in dependencias)
            or len(set(dependencias)) != len(dependencias)):
        raise ErrorConvivencia("El puente no identifica procedencias únicas de su folio G.", puente)
    if puente not in plan["alcance"]:
        raise ErrorConvivencia("El puente carece de procedencia del plan G.", puente)
    salidas = []
    for ref in dependencias:
        origen = declaradas.get(ref)
        if not isinstance(origen, dict) or origen.get("proyecto") != repo.proyecto:
            raise ErrorConvivencia(f"El puente atribuye {ref} a otro proyecto o carece de su procedencia.", puente)
        evidencia = origen.get("evidencia")
        anexos = f"{RAICES['G']}/modulos/{plan['modulo']}/anexos/"
        if (not isinstance(evidencia, str) or not evidencia.startswith(anexos)
                or not any(coincide(evidencia, alcance) for alcance in plan["alcance"])):
            raise ErrorConvivencia(f"El anexo de {ref} queda fuera del módulo o alcance de G.", puente)
        texto = repo.texto(evidencia)
        ramas = set(re.findall(rf"`({RAMA})`", texto))
        anclas = set(re.findall(rf"(?i)HEAD observado\s+`({OID})`", texto))
        if len(ramas) != 1 or len(anclas) != 1:
            raise ErrorConvivencia("Se requiere rama y ancla exactas y únicas en el anexo.", evidencia)
        rama, folio_fuente, _ = next(iter(ramas))
        ancla = next(iter(anclas))
        filas = re.findall(rf"^\|\s*{re.escape(ref)}\s*\|\s*`([^`]+)`\s*,?\s*([^|]*?)\|\s*`({OID})`\s*\|",
                           texto, re.MULTILINE)
        if len(filas) != 1:
            raise ErrorConvivencia(f"Falta una fuente inequívoca para {ref}.", evidencia)
        ruta, seccion, blob = filas[0]
        try:
            fuente = repo.en_arbol(ancla, historico=True)
            plan_fuente = fuente.plan(folio_fuente)
            ficha = re.fullmatch(rf"{FICHA}@r[1-9][0-9]*", ref)
            if ref == folio_fuente:
                ruta_esperada = plan_fuente["ruta"]
            elif ficha and ref in plan_fuente["funcionalidades"]:
                ruta_esperada = fuente.ficha(ref)["ruta"]
            else:
                raise ErrorConvivencia(f"{ref} no pertenece al folio fuente {folio_fuente}.", evidencia)
            if ruta != ruta_esperada or fuente.fuente(ruta).blob != blob:
                raise ErrorConvivencia(f"Ruta, revisión o blob de {ref} diverge de la fuente.", evidencia)
            if not repo.historico:
                rama_dueña = "refs/heads/" + rama
                punta = repo.commit_ref(rama_dueña)
                actual = repo.en_arbol(punta, historico=True)
                cambios = (ruta, plan_fuente["ruta"], plan_fuente["continuidad"], plan_fuente["estado_modulo"],
                           plan_fuente["evidencia"], *plan_fuente["contratos"])
                ancestro = repo.git("merge-base", ancla, punta).decode("ascii").strip()
                if ancestro != ancla or any(actual.fuente(p).blob != fuente.fuente(p).blob for p in set(cambios)):
                    raise ErrorConvivencia(f"La punta {punta} de {rama} cambió las entradas de {ref}; concilia el anclaje.",
                                           evidencia, "ANCLA_DESACTUALIZADA")
        except (ValueError, OSError) as exc:
            if isinstance(exc, ErrorConvivencia) and exc.ruta == evidencia:
                raise
            raise ErrorConvivencia(f"No se pudo cotejar el ancla de {ref}: {exc}.", evidencia) from exc
        proyeccion = {
            "ref": ref, "folio": folio_fuente, "dominio": folio_fuente[0], "proyecto": repo.proyecto,
            "ruta": ruta, "commit": ancla, "blob": blob, "rama": rama, "selector": seccion.strip(),
            "vigencia": "historica" if repo.historico else "vigente", "evidencia": evidencia,
        }
        proyeccion["huella"] = huella_datos({k: v for k, v in proyeccion.items() if k != "vigencia"})
        for clave in ("commit", "ruta", "blob", "selector", "huella"):
            if clave in origen and origen[clave] != proyeccion[clave]:
                raise ErrorConvivencia(f"Proyección alterada de {ref} en {clave}.", evidencia)
        salidas.append(proyeccion)
    return salidas


def _contrato_nativo(repo, identidad, tipo, ruta, estado, razon):
    procedencia = repo.fuente(ruta)
    return {
        "id": identidad.split("@", 1)[0], "referencia": identidad, "tipo": tipo,
        "ruta": ruta, "estado": estado, "razones": [razon], "blob": procedencia.blob,
        "commit": procedencia.ref, "sha256": procedencia.sha256,
    }


def informe_nativo(repo, operacion, *, sesion=None, funcionalidad=None, ruta=None):
    from .arboles import ErrorArbol
    from .convivencia import ErrorConvivencia, FICHA, campo, cubre_ruta, informe_error
    from .modelo import resultado, unicos

    salida = resultado(operacion)
    salida.update(
        perfil=repo.perfil,
        procedencia={"proyecto": repo.proyecto, "arbol": repo.arbol, "commit": repo.commit,
                     "head": repo.head, "rama": repo.rama, "taxonomia": repo.ruta_perfil,
                     "perfil_hash": repo.perfil_hash},
    )
    planes, fichas = [], []
    try:
        if sesion is not None:
            planes.append(repo.plan(sesion))
        elif funcionalidad is not None:
            fichas.append(repo.ficha(funcionalidad))
        elif ruta is not None:
            repo.lector.comprobar_ruta(ruta)
            for candidata in repo.listar("sdd/funcionalidades/"):
                match = re.fullmatch(rf"sdd/funcionalidades/({FICHA})(?:_[^/]+)?\.md", candidata)
                if match:
                    ficha = repo.ficha(match[1])
                    if any(coincide(ruta, objeto) for objeto in ficha["rutas"]) or ruta == ficha["ruta"]:
                        fichas.append(ficha)
            folios = repo.rutas_planes()
            for folio, plan_ruta in folios:
                if ruta == plan_ruta or campo(repo.texto(plan_ruta), "Estado") == "Activo":
                    plan = repo.plan(folio)
                    if (ruta in {plan_ruta, plan["evidencia"], plan["estado_modulo"], *plan["contratos"]}
                            or any(cubre_ruta(patron, ruta) for patron in plan["alcance"])):
                        planes.append(plan)
            if not planes and not fichas:
                raise ErrorConvivencia("Sin contrato nativo pertinente para ese destino.", ruta, "OBJETO_SIN_CONTRATO")
        else:
            candidatos = repo.rutas_planes()
            activos = repo.comprobar_activos(candidatos)
            for folio, plan_ruta in candidatos:
                if plan_ruta in activos.values():
                    planes.append(repo.plan(folio))

        for plan in planes:
            salida["contratos"].append(_contrato_nativo(repo, plan["folio"], "sesion", plan["ruta"],
                                                        plan["estado"], "plan canónico del folio"))
            salida["contratos"].extend(
                _contrato_nativo(repo, Path(r).stem, "modulo" if Path(r).stem.startswith("spec_") else "contrato",
                                 r, "referenciado", f"contrato técnico de {plan['folio']}")
                for r in plan["contratos"]
            )
            fichas.extend(repo.ficha(ref) for ref in plan["funcionalidades"])
            if plan["dominio"] == "G":
                salida["referencias_externas"].extend(_externas_nativas(repo, plan))
        salida["planes"] = planes
        if sesion is not None:
            plan = planes[0]
            estado = repo.texto(plan["estado_modulo"])
            paso = re.search(r"(?im)^(?:[-*]\s+)?siguiente paso:\s*(.+)$", estado)
            seccion = re.search(r"(?ims)^##\s+(?:\d+\.\s+)?Punto de continuación\s*\n(.+?)(?=\n##\s|\Z)", estado)
            salida.update(plan=plan, continuidad={
                "indice": plan["continuidad"], "estado": plan["estado_modulo"], "evidencia": plan["evidencia"],
                "siguiente": paso[1].strip() if paso else seccion[1].strip() if seccion else None,
            })

        for ficha in unicos(fichas):
            ref = ficha["referencia"]
            salida["contratos"].append(_contrato_nativo(repo, ref, "funcionalidad", ficha["ruta"],
                                                        ficha["estado"], "ficha nativa pertinente"))
            salida["criterios"].extend({"id": f"{ref}/{id_}", "descripcion": texto, "ruta": ficha["ruta"]}
                                       for id_, texto in ficha["criterios"].items())
        salida["contratos"] = unicos(salida["contratos"])
    except (ErrorArbol, ErrorConvivencia) as exc:
        salida.update(informe_error(operacion, exc))
    return salida
