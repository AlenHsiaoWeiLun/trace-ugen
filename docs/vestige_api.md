# VESTIGE API

Server: `python -m vestige` → `http://127.0.0.1:8100`. Interactive OpenAPI: `/docs`.
This documents the current server in `vestige/api.py`.

The current service uses one demo identity and a workspace allow-list. It is not a production login system.
Timestamps in the demo are assigned local ISO strings. Evidence and scope checks reject unauthorized
cross-workspace IDs; the generated OpenAPI describes request fields in full.

| Purpose | Endpoint |
|---|---|
| Workspaces | `GET /api/workspaces` |
| Overview | `GET /api/workspaces/{ws}/overview` |
| Sources and coverage | `GET /api/workspaces/{ws}/sources`, `GET /api/workspaces/{ws}/coverage` |
| Objects and history | `GET /api/workspaces/{ws}/objects`, `GET /api/objects/{oid}/history` |
| Events | `GET /api/workspaces/{ws}/events` |
| Event lead-up | `GET /api/events/{eid}/timeline?before_s=60` |
| Evidence | `GET /api/evidence/{eid}?ws={ws}` |
| Ask | `POST /api/workspaces/{ws}/ask` |
| Human review | `POST /api/events/{eid}/review` |
| Upload | `POST /api/workspaces/{ws}/sources` (multipart) |
| Background job | `GET /api/jobs/{jid}` |
| Lab options/history | `GET /api/lab/options`, `GET /api/lab/experiments` |
| Run/get experiment | `POST /api/lab/experiments`, `GET /api/lab/experiments/{xid}` |
| Markdown report | `GET /api/lab/experiments/{xid}/report.md` |

Example read-only investigation (also adds an audit entry):

```bash
curl -X POST http://127.0.0.1:8100/api/workspaces/campus/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What happened to my bicycle?"}'
```

The response includes `headline`, structured `steps`, `citations`, `gaps`, `subject` and tool-call details.
A citation points to a stored evidence ID/frame and, where available, a processed clip and playback offset.
An inferred candidate and an observed sighting are separate states. Human review accepts `confirmed`,
`rejected` or `uncertain`; it records the decision and note in the audit log.
