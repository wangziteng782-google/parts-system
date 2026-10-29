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
from .routes import sales as _sales
from .routes import feedback as _feedback
from .routes import inquiries as _inquiries
from .routes import inquiry_match as _inquiry_match
from .routes import product_relations as _product_relations
from .routes.oa_api import router as _oa_api_router

app.include_router(_oa_api_router)

__all__ = ["app"]
