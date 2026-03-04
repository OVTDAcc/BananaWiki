"""
BananaWiki – Route registration package.

Each sub-module groups related route handlers. Call :func:`register_all_routes`
to register every route group on the Flask application instance.
"""

from routes.auth import register_auth_routes
from routes.wiki import register_wiki_routes
from routes.users import register_user_routes
from routes.admin import register_admin_routes
from routes.chat import register_chat_routes
from routes.groups import register_group_routes
from routes.api import register_api_routes
from routes.uploads import register_upload_routes
from routes.errors import register_error_handlers


def register_all_routes(app):
    """Register all route groups and error handlers on *app*."""
    register_auth_routes(app)
    register_wiki_routes(app)
    register_user_routes(app)
    register_admin_routes(app)
    register_chat_routes(app)
    register_group_routes(app)
    register_api_routes(app)
    register_upload_routes(app)
    register_error_handlers(app)