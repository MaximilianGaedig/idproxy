# idproxy

`idproxy` allows accessing iCloud APIs using multiple Apple IDs, each routed through a per-account proxy. It's designed for fetching Find My reports.

At the moment it's created messily for a very specific use case, but can be modified easily to accommodate different use cases.
In the future I plan to create a public proxy instance out of this, so nobody will have to maintain macOS hardware for openhaystack-related projects.

It's also a good example for setting up multiple *transparently* proxied instances with a wireguard-proxy type setup.

## starting up the instances

To build and start the `idproxy` instances, execute the `multiple_instances.sh` script with the env vars `PROXIES_URL` and `INSTANCES`:

```bash
cd idproxy
PROXIES_URL="https://your-proxy-list-url.com/proxies.txt" INSTANCES=20 multiple_instances.sh up --build -d
```

By default, sockets allowing for access to the instance apis reside in /tmp/idproxy_sockets.

Each `idproxy` instance requires authentication with an Apple ID. You can add one Apple ID per instance.
To authenticate a virtual macintosh execute the following for each instance after it is spun up:
```bash
cd idproxy
docker compose -p idproxy_instance_1 exec -it api python idproxy.py -a -t
```

This process involves running an authentication command within the respective API container, which will prompt for Apple ID credentials and handle two-factor authentication. Upon successful authentication, necessary tokens are stored within the ./data/INSTANCE directories.

## client

The `idproxyclient` go package is a simple client that implements trying all instances until the request succeeds

## thanks

- to seemoo-lab for https://github.com/seemoo-lab/openhaystack and all their research!
- to biemster for the python scripts in https://github.com/biemster/FindMy
- to hrntknr for https://github.com/hrntknr/ofutun which made this project so much easier
- to Dadoum for https://github.com/Dadoum/anisette-v3-server

## disclaimer

This software is obviously not officially endorsed by Apple Inc. :)
