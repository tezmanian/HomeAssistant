# HomeAssistant

Home Assistant blueprints.

## Development checks

```
docker compose run --rm check   # YAML loads, !input defined, Jinja templates compile
docker compose run --rm lint    # yamllint
docker compose run --rm test    # heating season template tests
```
