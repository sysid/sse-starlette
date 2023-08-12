import asyncio
import logging

import pytest
from asgi_lifespan import LifespanManager
from sse_starlette import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

_log = logging.getLogger(__name__)
