# TROUBLESHOOTING.md

## Pip

```shell
TMPDIR=~/scratch/ PIP_CACHE_DIR=~/scratch/cache pip install 'sentence-transformers>=3.0'
```

## Systemd

> [!TIP]
> Commands can be run as the mnemo user via `systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait sh -c '...'`

### Stop all services

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user stop desktop-commander@2095 presence@2086 memory@2082 tool-cache@2088 hearth'
```

### Restart services

> [!WARNING]
> Restart **one at a time** to prevent **race condition** with io to **gateway.json**

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user restart desktop-commander@2095'

systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user restart presence@2086'

systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user restart memory@2082'

systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user restart tool-cache@2088'

systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user restart hearth'
```

### View unit status

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user status desktop-commander@2095 presence@2086 memory@2082 tool-cache@2088 hearth'
```

### View unit file + env

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user cat desktop-commander@2095 presence@2086 memory@2082 tool-cache@2088 hearth'

systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl --user show --property=EnvironmentFiles desktop-commander@2095'
```

### journalctl logs

```shell
# individual service
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat journalctl -l --since "90 seconds ago" --user -xelu desktop-commander@2095'

# stream all units
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat journalctl -l --since "0 seconds ago" --user -xelf \
    -u hearth -u tool-cache@2088 -u memory@2082 -u presence@2086 -u desktop-commander@2095'
```

### Disable

```shell
systemd-run --quiet --machine=mnemo@.host --user --collect --pipe --wait \
  sh -c 'PAGER=cat systemctl -l --user disable desktop-commander@2095 presence@2086 memory@2082 tool-cache@2088 hearth'
```
