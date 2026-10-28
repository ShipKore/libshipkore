---
description: 'Configure libshipkore: write the config file for carrier credentials, storage and the label file store, and check it works. Use when the user asks how to set up, connect a courier, add credentials, or when a tool says a credential is missing.'
when_to_use: 'Examples: "Set up Delhivery", "connect my Shiprocket account", "where do I put the API token", "missing credential api_token", "store orders in a database".'
---

# Set up libshipkore

Tracking needs no setup. Booking needs credentials, and those live in a **config file on the user's machine**, never in the chat.

**Hard rule:** do not ask the user to paste an API key, token or password to you, and do not write a real secret into any file yourself. Write references to environment variables (`${NAME}`) and tell the user to set them.

## 1. See where things stand

Call `list_providers`. `configured: true` means the server has credentials for that provider. If the provider they want is `false`, continue.

## 2. Write the config file

Create a JSON file (for example `~/.config/libshipkore/config.json`) with placeholders:

```json
{
  "providers": {
    "delhivery": {
      "credentials": { "api_token": "${DELHIVERY_TOKEN}" },
      "sandbox": true
    },
    "shiprocket": {
      "credentials": { "email": "${SHIPROCKET_EMAIL}", "password": "${SHIPROCKET_PASSWORD}" }
    }
  },
  "storage": "sqlite:////Users/you/.local/share/libshipkore/kore.db",
  "files": "s3://my-label-bucket/labels"
}
```

Then tell the user to set those environment variables in the shell or app that starts Claude Code, and to run `chmod 600` on the file. Only include the providers they use.

What each part means:

- **`providers.<slug>.credentials`**: Delhivery needs `api_token`. Shiprocket needs the `email` and `password` of an API user created in its panel under Settings > API (not the main login).
- **`sandbox`**: Delhivery has a staging environment with its own token; a staging token does not work on production. **Shiprocket has no sandbox**: its calls always act on the live account.
- **`storage`**: where orders, products, tracking and an audit trail of raw provider replies are kept. `memory://` (the default) forgets everything on restart. Use `sqlite:///path` for one machine, or any SQLAlchemy URL such as `postgresql://...` (needs `pip install "libshipkore[sql]"`).
- **`files`**: where label PDFs are kept, separate from the database, in any S3-compatible store (`s3://bucket/prefix`, or an object with `endpoint_url` and keys for MinIO and similar). Needs `libshipkore[s3]`. Without it labels are not copied and the courier's own link is returned, which can expire (Delhivery's after 24 hours).
- Unknown keys are rejected on purpose, so a typo such as `sandbx` is reported instead of ignored.

## 3. Point the plugin at it

In Claude Code run `/plugin`, open libshipkore, choose Configure and enter the file's path (or run `/plugin configure libshipkore@shipkore`). Then run `/reload-plugins`.

## 4. Check it

1. `list_providers`: the provider should now show `configured: true`, and `sandbox` should match the file.
2. Call `check_serviceability` for a pincode. A `HTTP 401` or "Invalid Token" error means the token is wrong or is for the other environment.
3. If a tool still reports a missing credential, the environment variable is probably not set in the process that started Claude Code.

## Running the server yourself

`libshipkore-mcp --config /path/config.json` runs it over stdio. `--transport http` serves `http://127.0.0.1:8765/mcp`, local only, and requires a bearer token (set `LIBSHIPKORE_MCP_TOKEN` to 16 or more characters, or one is generated and printed to stderr). It refuses any non-local address.

## How writes stay safe

Tools that book, cancel, schedule pickups or act on failed deliveries take two calls: a preview that changes nothing, then a confirmation with a token. This is a checkpoint, not proof that a person approved, so the agent must always show the preview and wait for a real yes.
