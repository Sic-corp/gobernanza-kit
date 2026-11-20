"""Traducción de los contratos SDD al inventario que usa el runner de sesiones."""

from collections import defaultdict
import hashlib
from pathlib import Path

from .modelo import Documento, coincide, diagnostico, referencia


def ruta_sesion_sdd(ruta):
    return ruta.startswith("sdd/registro/")


def _rutas_legadas(lector):
    from .documentos import json_estricto

    config = json_estricto(lector.leer("gobernanza/config.json").decode("utf-8"))
    patrones = config.get("documentos", ["sdd/spec_*.md", "sdd/funcionalidades/*.md",
                                        "sesiones/historial/*.md", "gobernanza/sesiones/historial/*.md"])
    return {ruta for ruta in lector.rutas
            if not ruta.startswith(("sdd/registro/", "sdd/operaciones/"))
            and ruta.split("/", 1)[0].casefold() != "playground"
            and any(coincide(ruta, patron) for patron in patrones)}


def _evolucion_legada(lector, ruta, anterior, actual):
    from .acuerdos import _capturar
    from .arboles import _git
    from .cierre import _estado_lista, _recibo
    from .documentos import json_estricto
    from .inicio import _actualizar_sesion
    from .modelo_sdd import leer

    if anterior is None or actual is None or anterior[0] != actual[0]:
        return False
    previo, _ = leer(anterior[1].decode("utf-8"))
    sesion = previo.get("id")
    if referencia(sesion) is None or not sesion.startswith(("S", "G")):
        return False
    datos, _ = leer(actual[1].decode("utf-8"))
    if datos.get("id") != sesion or datos.get("schema") != 1:
        return False
    imagen = anterior[1]
    ruta_inicio = f"sesiones/estado/{sesion}/acuerdo.json"
    if datos.get("inicio") != previo.get("inicio"):
        captura = json_estricto(lector.leer(ruta_inicio).decode("utf-8"))
        fuente = captura["ref_acuerdo"]
        _git(lector.raiz, "merge-base", "--is-ancestor", fuente, lector.commit or "HEAD")
        if (captura != _capturar(lector.raiz, sesion, fuente, captura["base"])
                or captura["ruta_sesion"] != ruta):
            return False
        imagen = _actualizar_sesion(imagen, ruta_inicio, fuente)
    if datos.get("cierre_preparado") != previo.get("cierre_preparado"):
        ruta_cierre = f"sesiones/estado/{sesion}/cierre.json"
        cierre = _recibo(json_estricto(lector.leer(ruta_cierre).decode("utf-8")), sesion)
        acuerdo = cierre["acuerdo"]
        _git(lector.raiz, "merge-base", "--is-ancestor", cierre["fuente_entrada"], lector.commit or "HEAD")
        _git(lector.raiz, "merge-base", "--is-ancestor", acuerdo["ref_acuerdo"], cierre["fuente_entrada"])
        if (acuerdo != _capturar(lector.raiz, sesion, acuerdo["ref_acuerdo"], acuerdo["base"])
                or acuerdo["ruta_sesion"] != ruta
                or cierre["huella_acuerdo"] != acuerdo["huella_acuerdo"]
                or cierre["huella_entradas"] != cierre["informe"]["huella_entradas"]):
            return False
        texto = imagen.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        imagen = _estado_lista(texto, ruta_cierre, cierre["huella_entradas"])
    return imagen == actual[1]


def auditar_legado(lector, operaciones):
    """Conserva el inventario V2 del último árbol anterior a la adopción."""
    from .arboles import LectorArbol

    origen = next((op for op in operaciones if any(c["accion"] == "migrar" for c in op["cambios"])), None)
    if origen is None:
        return []
    base = LectorArbol(lector.raiz, origen["base"])
    anteriores = _rutas_legadas(base)
    errores = []
    for ruta in sorted(anteriores | _rutas_legadas(lector)):
        try:
            anterior = base.entrada(ruta) if ruta in anteriores else None
            actual = lector.entrada(ruta)
            if anterior == actual or _evolucion_legada(lector, ruta, anterior, actual):
                continue
        except (ValueError, OSError, TypeError, KeyError, StopIteration):
            pass
        errores.append(diagnostico("LEGADO_SDD_DERIVA", ruta, "Inventario previo a la adopción SDD",
                                  "La fuente V2 cambió o se añadió después del corte de adopción.",
                                  "Conserva la fuente histórica y registra el cambio en el SDD."))
    return errores


def _fuente_migrada(repo, datos, legada):
    procedencia = datos.get("procedencia")
    if not procedencia:
        return not legada
    ruta = procedencia["ruta"]
    archivo = repo.segura(ruta)
    try:
        if archivo is not None and not archivo.is_symlink() and (legada is None or legada.ruta == ruta):
            if hashlib.sha256(archivo.read_bytes()).hexdigest() == procedencia["sha256"]:
                return True
    except OSError:
        pass
    repo.error("LEGADO_SDD_DERIVA", ruta, f"La fuente de {datos['ref']} difiere de la procedencia registrada.")
    return False


def integrar_documentos(repo):
    """El árbol consultado decide qué revisiones y qué metadatos están disponibles."""
    from .modelo_sdd import leer, validar_grafo

    documentos = {}
    for ruta in repo.rutas(["sdd/registro/*.md"]):
        archivo = repo.segura(ruta)
        if archivo is None:
            continue
        if archivo.is_symlink():
            repo.error("REGISTRO_SDD_INVALIDO", ruta, "El documento SDD debe ser un archivo regular.")
            continue
        try:
            datos, prosa = leer(archivo.read_bytes().decode("utf-8"))
        except (OSError, ValueError) as exc:
            repo.error("REGISTRO_SDD_INVALIDO", ruta, str(exc))
            continue
        documentos[Path(ruta).stem] = datos, prosa
    errores = validar_grafo(documentos)
    repo.errores.extend(errores)
    if errores:
        return

    def instalar(ref, datos, texto):
        anteriores = repo.por_id.get(datos["id"], [])
        if len(anteriores) > 1:
            return
        if anteriores:
            repo.documentos.remove(anteriores[0])
        doc = Documento(f"sdd/registro/{ref}.md", datos, texto)
        repo.documentos.append(doc)
        repo.por_id[doc.id] = [doc]

    funciones = defaultdict(list)
    compartidos = {}
    for ref, (datos, texto) in documentos.items():
        if datos["tipo"] == "funcionalidad":
            folio, revision = ref.split("@r")
            funciones[folio].append((int(revision), ref, datos, texto))
        elif datos["tipo"] in {"modulo", "sesion"}:
            previos = repo.por_id.get(ref, [])
            if datos["tipo"] == "modulo":
                proyeccion = dict(id=ref, version=1)
                if len(previos) == 1:
                    legado = previos[0]
                    if not _fuente_migrada(repo, datos, legado):
                        continue
                    proyeccion.update({campo: legado.datos[campo] for campo in (
                        "version", "funcionalidades", "objetos_compartidos", "dependencias",
                        "dependencias_propuestas", "funcionalidades_propuestas",
                    ) if campo in legado.datos})
                # El módulo conserva la propiedad y las revisiones renuevan el vínculo.
                if "objetos_compartidos" in proyeccion:
                    objetos = [dict(objeto, consumidores=list(objeto["consumidores"]))
                               for objeto in proyeccion["objetos_compartidos"]]
                    proyeccion["objetos_compartidos"] = objetos
                    compartidos[ref] = {objeto["ruta"]: objeto for objeto in objetos}
            else:
                if previos:
                    # Los recibos V2 conservan el camino exacto de su plan fuente.
                    continue
                proyeccion = dict(id=ref, funcionalidades=datos.get("funcionalidades", []))
            instalar(ref, dict(proyeccion, estado=datos["estado"]), texto)
    for folio, filas in funciones.items():
        filas.sort()
        publicados = [f for f in filas if f[2]["estado"] != "borrador"]
        actual = (publicados or filas)[-1][1]
        previas = repo.por_id.get(folio, [])
        legado = previas[0] if len(previas) == 1 else None
        comunes = dict(id=folio, revisiones=[n for n, *_ in filas],
                       criterios={str(n): d.get("criterios", []) for n, _, d, _ in filas})
        if legado is not None:
            fuentes = [ficha for _, _, ficha, _ in filas if "procedencia" in ficha]
            if fuentes and all(_fuente_migrada(repo, ficha, legado) for ficha in fuentes):
                comunes.update({campo: legado.datos[campo] for campo in ("sesiones", "evidencias_por_revision")
                                if campo in legado.datos})
        for revision, ref, ficha, prosa in filas:
            proyeccion = dict(comunes, revision_actual=revision, estado=ficha["estado"])
            proyeccion.update({campo: ficha[campo] for campo in ("modulo", "objetos", "dependencias") if campo in ficha})
            if ficha["estado"] != "borrador" and "objetos" in ficha and ficha.get("modulo") in compartidos:
                propios = []
                for ruta in ficha["objetos"]:
                    compartido = compartidos[ficha["modulo"]].get(ruta)
                    if compartido is None:
                        propios.append(ruta)
                    elif ref not in compartido["consumidores"]:
                        compartido["consumidores"].append(ref)
                proyeccion["objetos"] = propios
            repo.por_ref[ref] = Documento(f"sdd/registro/{ref}.md", proyeccion, prosa)
            if ref == actual:
                instalar(ref, proyeccion, prosa)


def comprobar_fase(raiz, commit, datos, *, reanudacion=False):
    """Coteja un informe preservado contra las entradas Git de la transición."""
    from .acuerdos import huella_obligaciones_materializadas
    from .arboles import LectorArbol, materializar
    from .cierre import _obligaciones_humanas
    from .contexto import contexto
    from .documentos import json_estricto
    from .modelo import diagnostico
    from .verificacion import _entradas, _hash

    estado = datos["estado"]
    if estado not in {"ejecucion", "pendiente_humana", "lista"}:
        return []
    etapa = "preparacion" if estado == "ejecucion" else "entrega"
    ref = datos["ref"]
    try:
        lector = LectorArbol(raiz, commit)
        candidatos = []
        for ruta in datos.get("evidencias", []):
            if ruta.endswith(".json"):
                informe = json_estricto(lector.leer(ruta).decode("utf-8"))
                if isinstance(informe, dict) and informe.get("etapa") == etapa and informe.get("sesion") == ref:
                    candidatos.append(informe)
        if not candidatos:
            raise ValueError(f"{ref} requiere un informe de {etapa} registrado en evidencias.")
        with materializar(raiz, commit) as copia:
            repo, entradas, autoridad = _entradas(copia, ref, reanudacion=reanudacion)
            contexto_sesion = contexto(copia.raiz, sesion=ref)
            if contexto_sesion["errores"]:
                raise ValueError(contexto_sesion["errores"][0]["mensaje"])
            requeridos = {p["selector"] for p in contexto_sesion["pruebas_declaradas"]}
            for informe in candidatos:
                if (informe.get("codigo") != 0 or informe.get("schema") != 1
                        or informe.get("huella_acuerdo") != autoridad["huella_acuerdo"]
                        or informe.get("proyecto") != repo.config["proyecto"]
                        or informe.get("huella_informe") != _hash({k: v for k, v in informe.items() if k != "huella_informe"})
                        or not requeridos or set(informe.get("casos_ejecutados", [])) != requeridos):
                    continue
                if etapa == "preparacion":
                    if informe.get("preparacion_satisfecha") is True:
                        obligaciones = huella_obligaciones_materializadas(
                            copia.raiz, reanudar_sesion=ref if reanudacion else None,
                        )
                        if informe.get("huella_obligaciones") == obligaciones:
                            return []
                elif informe.get("pruebas_aprobadas") is True and informe.get("huella_entradas") == _hash(entradas):
                    if estado == "lista":
                        criterios = {c["referencia"] for c in contexto_sesion["criterios"]}
                        _obligaciones_humanas(datos, informe["acuerdo"], informe, criterios)
                    return []
        raise ValueError(f"La evidencia de {etapa} enlazada por {ref} ha perdido vigencia.")
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return [diagnostico("FASE_SDD", f"sdd/registro/{ref}.md", f"Evidencia de {etapa} vigente",
                            str(exc), "Vincula el informe del candidato y resuelve las obligaciones de la fase.")]
