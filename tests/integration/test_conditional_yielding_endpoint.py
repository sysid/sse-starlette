import asyncio
import logging

import pytest
from asgi_lifespan import LifespanManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from sse_starlette import EventSourceResponse

_log = logging.getLogger(__name__)
