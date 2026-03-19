# README.md

Provides a presence wrapper

> [!TIP]
> **🎆 Getting set up**
> [docs/QUICK_START.md](docs/QUICK_START.md)
>
> [docs/CONFIGURE.md](docs/CONFIGURE.md)

## Detail

> [!TIP]
> **🏗️ Design overview**
> [docs/DESIGN.md](docs/DESIGN.md)

```mermaid
graph LR
    subgraph clients [client devices]
        App[Frontend / TUI]
    end

    App <-->|TCP · NDJSON| Hearth
    App <-->|wss · realtime| xAI_RT[xAI realtime]

    subgraph host [host]
        Hearth[Hearth daemon] --> Agent[Agent]
        Agent --> xai_client[xAI client]
        Hearth --- Qdrant[(qdrant)]
    end

    xai_client <-->|TLS| server[xAI server]

    subgraph cloud [☁️]
        server -->|TLS · Bearer| CF1[CF Tunnel]
        server -->|TLS · Bearer| CF2[CF Tunnel]
        xAI_RT
    end

    subgraph dc [desktop-commander]
        CF1 --> GW1[mcp_gateway] --> proxy1[mcp-proxy]
    end

    subgraph cp [cozy-presence]
        CF2 --> GW2[mcp_gateway] --> proxy2[mcp-proxy]
    end

```

## Usage & Compliance

mnemo is a user-driven presence wrapper around the official xAI API — not an autonomous agent framework. All operations require explicit user initiation.

- **Data persistence** — any data stored locally (Qdrant, JSONL) is opt-in and fully user-controlled. mnemo does not persist model outputs or conversation content without user consent.
- **Sessions** — each user and device maintains its own authenticated xAI session. mnemo does not multiplex multiple users through a single identity.
- **Transport** — Cloudflare tunnels are used for secure inbound transport only. They do not alter authentication or obscure client identity to xAI.
- **Affiliation** — mnemo is not affiliated with or endorsed by xAI.
- **Acceptable use** — mnemo is intended for personal assistants, presence, and productivity tooling. It must not be used for scraping, impersonation, or prohibited automation.

## Troubleshooting

> [!TIP]
> **🫠 Assessing damage**
> [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## Contributing to the project

> [!NOTE]
> **🔥 IMPORTANT**
> Before begining, </br>
> please review the following

>[!TIP]
> **📖 Project guidelines**
> [CONTRIBUTING.md](./docs/CONTRIBUTING.md)

>[!TIP]
> **📖 Pending tasks**
> [TODO.md](./docs/TODO.md)

>[!TIP]
> **🫡 Documentaiton for deps**
> [docs/RESOURCES.md](docs/RESOURCES.md)

---

>[!NOTE]
> **🌸 Keeping Cozy**
> Once you're contributing, </br>
> please Update the following

>[!TIP]
> **📖 Credit yourself**
> [AUTHORS.md](./docs/AUTHORS.md)
