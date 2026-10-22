# Development documentation

For someone changing `edna2dwc` rather than running it. User-facing pages are in [`docs/`](../README.md), and setup, tests and style are in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

|  |  |
| --- | --- |
| [`vocabulary.md`](vocabulary.md) | What each term means, and the words that mean something else here. Read this first |
| [`architecture.md`](architecture.md) | The intermediate table, the packaging steps, the module map |
| [`decisions.md`](decisions.md) | Decisions and their corresponding tradeoffs. Add to this list when necessary |
| [`ci.md`](ci.md) | Auditing the workflows, and pinning actions and images |

Behavior goes in the user-facing page for its area. Structure goes in `architecture.md`. A decision goes in `decisions.md`. None of it goes in a comment.
