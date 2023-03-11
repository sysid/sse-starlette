
<a id='changelog-1.3.3'></a>
# 1.3.3 — 2023-03-11

removal of requirements.txt
python 3.11 added to tox

<a id='changelog-1.3.0'></a>
# 1.3.0 — 2023-02-09

- replace anyio.sleep() with anyio.Event

<a id='changelog-1.2.1'></a>
# 1.2.1 — 2022-11-15

- add support for custom async iterable objects
  https://github.com/sysid/sse-starlette/pull/43

<a id='changelog-1.1.6'></a>
# 1.1.6 — 2022-07-31

- replace `asyncio.sleep()` with `anyio.sleep`

<a id='changelog-1.1.4'></a>
# 1.1.4 — 2022-07-31

- introduced scriv for changelog management


# 1.1.3 (2022-07-26)
- fix: py.typed was missing in PyPi distribution

# 1.1.0 (2022-07-25)
- allow user to set cache-control header for fan-out use-case:
  Ref: https://www.fastly.com/blog/server-sent-events-fastly

# 1.0.0 (2022-07-24)
- drop support for python 3.6 and 3.7
- removed unused private attribute `_loop` from class `EventSourceResponse`
- updated example in README.md

# 0.10.3 (2022-01-25)
- fix: use starlette's code to set proper content-type and charset
- fix: update examples

# 0.10.0 (2021-12-14)
- base EventSourceResponse on latest starlette StreamingResponse (0.17.1) and use anyio
- breaking change: `response.wait()` and `response.stop_streaming()` removed

# 0.9.0 (2021-10-09)
- add sse comment support

# 0.8.1 (2021-09-30)
- minimum required python version relaxed to python 3.6

# 0.8.0 (2021-08-26)
- using module-based logger instead of uvicorn logger

# 0.7.2 (2021-04-18)
- refactoring: Github Actions introduced into build pipeline

# 0.6.2 (2020-12-19)
- fix: correct shutdown signal handling in case of an endpoint which only yields sporadic messages

# 0.6.1 (2020-10-24)
- updated example with proper error handling

# 0.6.0 (2020-10-24)
- In case [uvicorn](https://www.uvicorn.org/) is used: monkeypatch uvicorn signal-handler,
  in order to gracefully shutdown long-running handlers/generators.
