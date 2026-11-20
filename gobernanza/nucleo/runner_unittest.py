"""Proceso unittest estructurado de F-0105. Solo se ejecuta a petición explícita."""

import json
import os
from pathlib import Path
import sys
import traceback
import unittest


def ejecutar(job):
    raiz = Path(job["raiz"])
    destino = Path(job["salida"])
    os.chdir(job["cwd"])
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(raiz))
    loader = unittest.TestLoader()
    suite = loader.discover(job["inicio"], pattern=job["patron"], top_level_dir=job.get("top"))

    def aplanar(grupo):
        for caso in grupo:
            if isinstance(caso, unittest.TestSuite):
                yield from aplanar(caso)
            else:
                yield caso

    casos = list(aplanar(suite))
    inventario = [c.id() for c in casos]
    requeridos = job["obligatorios"]
    informe = {"casos_descubiertos": inventario, "casos_ejecutados": [], "resultados": [],
               "errores_descubrimiento": loader.errors, "ausentes": sorted(set(requeridos) - set(inventario))}

    def guardar():
        destino.write_text(json.dumps(informe, ensure_ascii=False), encoding="utf-8")

    guardar()
    if loader.errors or informe["ausentes"] or not requeridos or len(inventario) != len(set(inventario)):
        return 1

    class Registro(unittest.TextTestResult):
        def startTest(self, test):
            super().startTest(test)
            informe["casos_ejecutados"].append(test.id())
            informe["resultados"].append({"selector": test.id(), "estado": "iniciado", "detalle": ""})
            guardar()

        def registrar(self, test, estado, detalle=""):
            registro = next(r for r in informe["resultados"] if r["selector"] == test.id())
            registro.setdefault("eventos", []).append(dict(estado=estado, detalle=detalle))
            prioridad = {"iniciado": 0, "aprobado": 1, "fallo": 2, "fallo_esperado": 2,
                         "omitido": 3, "exito_inesperado": 3, "error": 4}
            if prioridad[estado] >= prioridad[registro["estado"]]:
                registro.update(estado=estado, detalle=detalle)
            guardar()

        def addSuccess(self, test):
            super().addSuccess(test)
            self.registrar(test, "aprobado")

        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.registrar(test, "fallo", self._exc_info_to_string(err, test))

        def addError(self, test, err):
            super().addError(test, err)
            self.registrar(test, "error", self._exc_info_to_string(err, test))

        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            if err is not None:
                self.registrar(test, "fallo" if issubclass(err[0], test.failureException) else "error",
                               self._exc_info_to_string(err, test))

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self.registrar(test, "omitido", reason)

        def addExpectedFailure(self, test, err):
            super().addExpectedFailure(test, err)
            self.registrar(test, "fallo_esperado", self._exc_info_to_string(err, test))

        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test)
            self.registrar(test, "exito_inesperado")

    elegidos = unittest.TestSuite(c for c in casos if c.id() in requeridos)
    resultado = unittest.TextTestRunner(verbosity=job.get("verbosity", 2), buffer=job.get("buffer", False),
                                      resultclass=Registro).run(elegidos)
    informe["completa"] = True
    guardar()
    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        sys.exit(ejecutar(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
