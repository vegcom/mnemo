# QUICK_START.md

## Base environment

```shell
# prevent logout stopping services
loginctl enable-linger mnemo
```

## pre-install

```shell
# install desktop-commander globally for the mnemo user
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait /bin/bash -lc \
  'source /opt/nvm/nvm.sh && npm install -g --ignore-scripts @wonderwhy-er/desktop-commander'

# deploy desktop-commander config
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'cp -v ~/git/mnemo/deploy/desktop_commander_config.json /etc/mnemo/desktop_commander_config.json'
```

## pip / python env

```shell
conda env create -f ./environment.yml
pip install -e '.[presence,tool-cache,server,app]'
```

## deploy systemd units

>[!TIP]
> **Configure services first** — [docs/CONFIGURE.md](./CONFIGURE.md)

`gateway@.service` is the shared template for all MCP gateway services. Deploy it once, symlink per service.

```shell
# deploy shared gateway template
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'cp -v ~/git/mnemo/deploy/gateway@.service ~/.config/systemd/user/gateway@.service'

# symlink per service
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'cd ~/.config/systemd/user && \
    ln -sf gateway@.service desktop-commander@.service && \
    ln -sf gateway@.service presence@.service && \
    ln -sf gateway@.service memory@.service && \
    ln -sf gateway@.service tool-cache@.service'

# hearth (standalone)
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'cp -v ~/git/mnemo/deploy/hearth.service ~/.config/systemd/user/hearth.service'
```

## deploy confs

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait sh -c '
  cp -v ~/git/mnemo/deploy/desktop-commander.conf /etc/mnemo/desktop-commander.conf
  cp -v ~/git/mnemo/deploy/presence.conf          /etc/mnemo/presence.conf
  cp -v ~/git/mnemo/deploy/memory.conf            /etc/mnemo/memory.conf
  cp -v ~/git/mnemo/deploy/tool-cache.conf        /etc/mnemo/tool-cache.conf
  cp -v ~/git/mnemo/deploy/hearth.conf            /etc/mnemo/hearth.conf
'
```

```shell
# secrets (fill in values from mcp-secrets.conf.example first)
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'cp -v ~/git/mnemo/deploy/mcp-secrets.conf /etc/mnemo/mcp-secrets.conf && \
         chmod -v 660 /etc/mnemo/mcp-secrets.conf'
```

## reload daemon

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'systemctl --user daemon-reload'
```

## start services

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait sh -c '
  systemctl --user enable --now desktop-commander@2095
  systemctl --user enable --now presence@2086
  systemctl --user enable --now memory@2082
  systemctl --user enable --now tool-cache@2088
  systemctl --user enable --now hearth
'
```

> Ports (2095, 2086, etc.) are passed as `MCP_LOCAL_PORT` via the `@<port>` specifier — adjust to suit your setup.

---

>[!TIP]
> **For any issue, consult**
>
> [docs/TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
