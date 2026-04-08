from .agricoltura import AgricolturaTabMixin
from .azienda import AziendaTabMixin, MovimentiTabMixin, StoricoTabMixin
from .attrezzature import AttrezzatureTabMixin
from .form_helpers import FormHelpersMixin
from .macchinari import MacchinariTabMixin
from .zootecnia import CarneTabMixin, LatteTabMixin, ZootecniaTabMixin

__all__ = [
	"AgricolturaTabMixin",
	"AziendaTabMixin",
	"AttrezzatureTabMixin",
	"CarneTabMixin",
	"FormHelpersMixin",
	"LatteTabMixin",
	"MacchinariTabMixin",
	"MovimentiTabMixin",
	"StoricoTabMixin",
	"ZootecniaTabMixin",
]
