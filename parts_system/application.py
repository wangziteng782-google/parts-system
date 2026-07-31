from .bootstrap import app

# Importing each feature module registers its existing routes on the shared app.
from .routes import products as _products
from .routes import pages as _pages
from .routes import catalog as _catalog
from .routes import variants as _variants
from .routes import legacy_params as _legacy_params
from .routes import image_library as _image_library
from .routes import logs as _logs
from .routes import health as _health

__all__ = ["app"]
