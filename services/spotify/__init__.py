"""Namespace Spotify (serviços). Re-exporta API pública para compatibilidade."""
__all__ = []
def _reexport(modname: str) -> None:
    try:
        module = __import__(f"{__name__}.{modname}", fromlist=["*"])
        for k, v in module.__dict__.items():
            if not k.startswith("_"):
                globals()[k] = v
                __all__.append(k)
    except Exception:
        pass

# inclui 'core' (era o antigo services/spotify.py) + restantes módulos
for _m in ["core","auth","client","errors","models","mappers","queries",
           "search","albums","radio","genres","lookup","push","session_push"]:
    _reexport(_m)
del _reexport
