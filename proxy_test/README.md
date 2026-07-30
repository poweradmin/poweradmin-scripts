# Proxy handling integration test

End to end check for `Poweradmin\Infrastructure\Network\ProxyContext`, covering issue #1188:

- `HTTP_PROXY` routes outbound requests through the configured proxy
- `NO_PROXY` exact-host entries bypass the proxy
- `NO_PROXY` CIDR entries bypass the proxy

`tests/unit/Infrastructure/Network/ProxyContextTest.php` in the main repo already covers the class at unit level.
What this adds is proof at the socket level that a real request goes where it should.

## Running

```bash
./scripts/proxy_test/run_proxy_test.sh
```

Exits 0 on `ALL TESTS PASSED`, 1 otherwise.

## Requirements

- **This repo must sit inside a poweradmin checkout.** `proxy_harness.php` loads `../../vendor/autoload.php`, so
  the app and its Composer dependencies have to be one directory up.
- `php`, `python3` and `bash` with `/dev/tcp` support on `PATH`.
- TCP ports **18888** (proxy stub) and **19999** (target stub) must be free. They are hardcoded with no fallback,
  so the run fails if something else holds them.

Both stubs bind loopback only and are killed on exit. Logs go to the system temp directory.

## Layout

| File | Role |
|---|---|
| `run_proxy_test.sh` | orchestrator: starts the stubs, runs the four cases, asserts on body and log lines |
| `proxy_harness.php` | calls `ProxyContext::httpOptionsFor($url)`, fires the request, prints options and body |
| `proxy_stub.py` | forward-proxy stub; logs the request line, always answers `FROM_PROXY!` |
| `target_stub.py` | target server stub; logs the request line, answers `FROM_TARGET!` |

The stubs do not forward upstream. The test only needs to know which one was reached.
