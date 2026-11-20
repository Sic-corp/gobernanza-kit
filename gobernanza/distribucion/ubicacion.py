"""Reconoce procedencia histórica para transiciones a la ruta fija."""

import os


def origen(raiz):
    from .gestor import (
        BASE_FIJA, CAPACIDAD_RUTA_FIJA, MAPA_UBICABLE,
        ErrorGestor, _CLASICA, _FIJA, _Ubicacion, _capturar,
        _mapa_ubicable, _slot, _selector_valido, _leer_json,
    )

    candidatos = [_CLASICA, _Ubicacion(BASE_FIJA)]
    firma = None
    if os.path.lexists(raiz / MAPA_UBICABLE):
        try:
            historica, firma = _mapa_ubicable(raiz)
        except (OSError, ValueError):
            # Un mapa ajeno no decide el destino. Un kit antiguo que dependía
            # de él será diagnosticado al comprobar su bloque gestionado.
            pass
        else:
            if historica not in candidatos:
                candidatos.append(historica)
    activas = []
    for ubicacion in candidatos:
        selector = _leer_json(raiz, ubicacion.activo)
        if selector is not None:
            activas.append((ubicacion, _selector_valido(selector)))
        elif _capturar(raiz, ubicacion.activo) is not None:
            raise ErrorGestor(f"Selector de instalación inválido: {ubicacion.activo}.")
    if len(activas) > 1:
        raise ErrorGestor("Hay más de una instalación activa; revisa su procedencia antes de actualizar.")
    if not activas:
        return _FIJA, None
    ubicacion, selector = activas[0]
    slot = _slot(raiz, selector, ubicacion)
    if ubicacion.base == BASE_FIJA:
        reconocida = _FIJA if (slot / CAPACIDAD_RUTA_FIJA).is_file() else ubicacion
        return reconocida, None
    return ubicacion, firma if ubicacion.ubicable else None
