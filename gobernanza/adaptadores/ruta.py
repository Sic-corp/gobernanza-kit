"""Entrada de la ruta de desarrollo para personas y agentes del candidato."""

import json
import sys

from ..nucleo.arboles import LectorArbol
from ..nucleo.documentos import json_estricto
from ..nucleo.inicio import guardar_documentos
from ..nucleo.modelo import coincide, resultado


CONFIG = "gobernanza/config.json"


def opciones(verbos, comunes):
    ruta = verbos.add_parser("ruta", help="Planificar metas, consultar el siguiente hito y vincular sesiones")
    comunes(ruta)
    operaciones = ruta.add_subparsers(dest="accion_ruta", required=True)
    for nombre in ("plantilla", "consultar", "registrar", "vincular", "configurar"):
        op = operaciones.add_parser(nombre)
        comunes(op)
        if nombre in {"registrar", "vincular", "configurar"}:
            op.add_argument("--aplicar", action="store_true", help="Guardar en Git la operación propuesta")
        if nombre == "plantilla":
            op.add_argument("tipo", choices=["meta", "objetivo"])
        if nombre == "consultar":
            op.add_argument("--hasta", help="ID o título del destino")
        if nombre == "registrar":
            op.add_argument("--entrada", required=True, help="Archivo JSON con la operación de planificación")
        if nombre == "vincular":
            op.add_argument("--sesion", required=True)
            op.add_argument("--base", help="SHA de la lectura del agente, para detectar actualizaciones concurrentes")
            op.add_argument("--destino", required=True, action="append", help="Una meta u objetivos de una misma meta. Repetible.")
        if nombre == "configurar":
            op.add_argument("--solucion", action="append", help="Ruta de producto relativa al repositorio. Repetible.")
            op.add_argument("--pruebas", action="append", help="Ruta de pruebas relativa al repositorio. Repetible.")
    tablero = verbos.add_parser("tablero", help="Abrir el tablero local del repositorio en el navegador")
    comunes(tablero)
    tablero.add_argument("--puerto", type=int, default=0, help="Puerto local, 0 elige uno disponible")
    tablero.add_argument("--sin-abrir", action="store_true", help="Imprimir la URL sin abrir el navegador")


def completar_raices_de_inicio(raiz, base):
    """Recoge las ubicaciones que falten al preparar un proyecto que adoptó la ruta."""
    lector = LectorArbol(raiz, "HEAD")
    entrada = lector.entrada(CONFIG)
    if not entrada:
        return
    config = json_estricto(entrada[1].decode())
    if config.get("ruta_desarrollo_requerida") is not True:
        return
    faltan = [campo for campo in ("solucion", "pruebas") if not config.get("raices", {}).get(campo)]
    if faltan:
        if base or not sys.stdin.isatty():
            opciones = " ".join("--" + campo + " RUTA" for campo in faltan)
            raise ValueError(f"Completa las ubicaciones con ruta configurar {opciones} --aplicar antes de iniciar.")
        configurar(raiz, solucion=None, pruebas=None, aplicar=True)


def configurar(raiz, *, solucion, pruebas, aplicar):
    lector = LectorArbol(raiz, "HEAD")
    entrada = lector.entrada(CONFIG)
    if entrada is None:
        config = {"schema": 1, "proyecto": lector.raiz.name, "raices": {"controles": [CONFIG]},
                  "verificadores": [], "salidas": ["sesiones/estado/", "sesiones/evidencias/"]}
    else:
        config = json_estricto(entrada[1].decode())
        if not isinstance(config, dict) or type(config.get("schema")) is not int or config["schema"] != 1:
            raise ValueError(f"Se requiere la configuración del kit local de esquema 1 en {CONFIG}.")
    raices = config.setdefault("raices", {})
    for campo in ("solucion", "pruebas"):
        ubicaciones = solucion if campo == "solucion" else pruebas
        if ubicaciones is None and raices.get(campo):
            existentes = raices[campo]
            if not isinstance(existentes, list) or not all(isinstance(r, str) and r for r in existentes):
                raise ValueError(f"Revisa --{campo} en {CONFIG}.")
            for existente in existentes:
                lector.comprobar_ruta(existente.removesuffix("/"))
            continue
        if not ubicaciones and aplicar and sys.stdin.isatty():
            print(f"Directorio de {campo} relativo a la raíz del candidato: ", end="", file=sys.stderr, flush=True)
            ubicaciones = [input().strip()]
        if not ubicaciones or not all(ubicaciones):
            raise ValueError(f"Indica --{campo} con su ubicación en el proyecto candidato.")
        destinos = []
        for valor in ubicaciones:
            nombre = lector.comprobar_ruta(valor.removesuffix("/"))
            es_archivo = nombre in lector.entradas or any(c in nombre for c in "*?[")
            destinos.append(nombre if es_archivo else nombre + "/")
        raices[campo] = list(dict.fromkeys(destinos))
    solucion, pruebas = raices["solucion"], raices["pruebas"]
    if any(coincide(p.rstrip("/"), s) or coincide(s.rstrip("/"), p) for s in solucion for p in pruebas):
        raise ValueError("Indica ubicaciones separadas para --solucion y --pruebas.")
    config["ruta_desarrollo_requerida"] = True
    salida = dict(resultado("ruta configurar"), base=lector.commit, raices=raices,
                  resumen="Raíces de solución y pruebas configuradas para la vinculación de sesiones.")
    if aplicar:
        imagen = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
        salida["commit"] = guardar_documentos(raiz, {CONFIG: imagen}, "Configurar la ruta de desarrollo del proyecto",
                                              esperado=lector.commit)
    return salida


def despachar(raiz, args, leer_entrada):
    accion = args.accion_ruta
    if accion == "configurar":
        return configurar(raiz, solucion=args.solucion, pruebas=args.pruebas, aplicar=args.aplicar)
    if accion == "plantilla":
        plantilla = {"accion": "crear_" + args.tipo, "titulo": "", "criterio": ""}
        if args.tipo == "objetivo":
            plantilla["meta"] = "META-01"
        return dict(resultado("ruta plantilla"), plantilla=plantilla,
                    resumen=json.dumps(plantilla, ensure_ascii=False, indent=2))
    if accion == "vincular":
        from ..nucleo.registro_sdd import vincular_ruta
        return vincular_ruta(raiz, args.sesion, args.destino, base=args.base, aplicar=args.aplicar)
    from ..nucleo.ruta_desarrollo import RUTA, leer_ruta, operar_ruta, proyeccion_ruta
    if accion == "registrar":
        return operar_ruta(raiz, leer_entrada(raiz, args.entrada), aplicar=args.aplicar)
    lector = LectorArbol(raiz, "HEAD")
    entrada = lector.entrada(RUTA)
    metas = leer_ruta(entrada[1].decode()) if entrada else []
    vista = proyeccion_ruta(metas, args.hasta)
    siguiente = vista["siguiente"]
    if siguiente:
        tarea = ("Confirmar el resultado de " if siguiente.get("confirmar") else "") + siguiente["titulo"]
        resumen = f"Siguiente hito · {siguiente['id']} · {tarea} ({siguiente['estado']})"
    else:
        resumen = "La ruta está cubierta." if metas else "Aún no hay metas registradas."
    if args.hasta:
        for hito in vista["recorrido"]:
            tarea = ("Confirmar el resultado de " if hito.get("confirmar") else "") + hito["titulo"]
            resumen += f"\n{hito['id']} · {tarea} ({hito['estado']})"
    return dict(resultado("ruta consultar"), **vista, base=lector.commit, resumen=resumen)
