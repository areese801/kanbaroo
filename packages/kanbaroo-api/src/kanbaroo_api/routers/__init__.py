"""
FastAPI routers for the ``/api/v1`` surface.

Each submodule owns one resource and stays thin: validate input,
resolve dependencies (session, actor), call one service function,
return the response. Audit emission lives in the service layer, not
here.
"""
