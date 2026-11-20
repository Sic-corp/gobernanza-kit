"""Validación estructural de F-0102; no ejecuta verificadores ni acepta entrega."""

from pathlib import Path

from .arboles import ErrorArbol, materializar
from .convivencia import ErrorConvivencia, informe_error, seleccionar_perfil
from .documentos import cargar, informe_nativo
from .modelo import diagnostico, resultado


def validar(raiz, *, arbol="worktree", historico=False):
    try:
        nativo = seleccionar_perfil(raiz, arbol, historico=historico)
        if nativo is not None:
            return informe_nativo(nativo, "validar")
        if (Path(raiz) / ".git").exists():
            from .registro_sdd import auditar
            errores = auditar(raiz, arbol)
            if errores:
                return resultado("validar", errores)
            with materializar(raiz, arbol) as vista:
                repo = cargar(vista.raiz)
        else:
            repo = cargar(raiz)
    except (ErrorConvivencia, ErrorArbol) as exc:
        return informe_error("validar", exc)
    except (TypeError, ValueError, OSError) as exc:
        return resultado("validar", [diagnostico("RAIZ_INVALIDA", str(raiz), "Raíz de proyecto legible",
                                              str(exc), "Indica una carpeta de proyecto válida.")])
    salida = resultado("validar", repo.errores, repo.pendientes)
    salida["contratos"] = [d.contrato(razones=["inventario documental declarado"])
                           for d in repo.documentos]
    salida["criterios"] = [c for d in repo.documentos if d.tipo == "funcionalidad"
                          for revision in d.datos["revisiones"]
                          for c in d.criterios(revision)]
    salida["pruebas_declaradas"] = repo.pruebas
    salida["referencias_externas"] = [dict(origen, ref=ref) for ref, origen in repo.externas.items()]
    return salida
