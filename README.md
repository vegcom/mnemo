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

> [!NOTE]
> **📖 AI-powered documentation**
> 
>  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/vegcom/mnemo) 

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

## Compliance & Safety

mnemo is a user-driven presence wrapper around the official xAI API. It does not perform autonomous actions, does not self-initiate tasks, and does not invoke tools without explicit user instruction. All operations require clear, intentional user direction.

mnemo does not alter, mask, or impersonate xAI model identity. All model responses are passed through unmodified, and mnemo does not present itself as an xAI product or service.

mnemo does not store user messages or model outputs without explicit consent. Any persisted data (e.g., via Qdrant) is opt-in, user-controlled, and remains local unless the user explicitly configures otherwise.

Each user/device maintains its own authenticated xAI session. Realtime connections are not shared or multiplexed across clients; every connection corresponds to a single user/device identity.

Cloudflare tunnels are used solely for secure transport and do not obscure client identity or modify authentication.

mnemo must not be used for scraping, impersonation, or prohibited automation. It is a toolkit for building user-directed assistants, not autonomous agents.

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
