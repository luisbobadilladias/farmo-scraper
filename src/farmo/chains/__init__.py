from . import catedral, farmacenter, farmaoliva, puntofarma

# name -> module; every module exposes search(query: str) -> list[RawProduct]
CHAINS = {
    "farmacenter": farmacenter,
    "catedral": catedral,
    "farmaoliva": farmaoliva,
    "puntofarma": puntofarma,
}

