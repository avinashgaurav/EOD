"""Post the day's update to Slack, Teams or Linear: the receipt's Send button.

This is the one module in the engine that opens a network connection, and it is
reached only through `extract.py --send`, which eod.lua runs when you press Send.
Destinations come from send.txt (see config.load_send_targets); with no file
there is no button, and nothing here ever runs.

Webhook URLs and the Linear key are secrets. No message below includes them:
every error names the destination and what went wrong, never its address, and
anything unexpected is reported by exception type only, never by its text.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import CACHE, SEND_LABELS, app_path, load_send_targets
from .hide import apply_hide
from .features import redact
from .render.text import to_standup

TIMEOUT = 15
LINEAR_API = "https://api.linear.app/graphql"
# commentCreate wants the issue's UUID; issue(id:) accepts either that or the
# readable identifier (ENG-123), so the send resolves it first.
LINEAR_ISSUE_QUERY = "query EodIssue($id: String!) { issue(id: $id) { id } }"
LINEAR_MUTATION = ("mutation EodComment($input: CommentCreateInput!) "
                   "{ commentCreate(input: $input) { success } }")


class SendError(Exception):
    """A failure that is safe to show: it never carries a secret."""


class _NoRedirect(HTTPRedirectHandler):
    """A webhook that redirects is misconfigured, and following it would carry
    the Linear key's Authorization header to wherever it points. Refusing makes
    the 30x surface as an HTTPError instead."""

    def redirect_request(self, *a, **k):
        return None


_OPENER = build_opener(_NoRedirect)


def urlopen(req, timeout):
    """The one call that leaves the Mac. A name of our own so tests replace it."""
    return _OPENER.open(req, timeout=timeout)


def _post(url, payload, headers=None):
    h = {"Content-Type": "application/json", "User-Agent": "EOD"}
    h.update(headers or {})
    try:
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST")
        with urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", "replace")
    except HTTPError as e:
        try:
            if 300 <= e.code < 400:
                raise SendError("redirected (HTTP %d), not followed" % e.code)
            # Slack answers with a short reason ("invalid_token", "no_service"),
            # which is the useful part, and never echoes the URL in it.
            try:
                reason = e.read().decode("utf-8", "replace").strip()
            except Exception:
                reason = ""
            raise SendError("HTTP %d%s" % (e.code, (" " + reason[:60]) if reason else ""))
        finally:
            e.close()
    except URLError as e:
        if isinstance(e.reason, OSError):       # DNS, refused, TLS: the type says enough
            raise SendError("could not connect (%s)" % type(e.reason).__name__)
        raise SendError("could not connect")
    except OSError as e:                        # a timeout mid-read, a reset connection
        raise SendError("network error (%s)" % type(e).__name__)
    except ValueError:                          # a malformed URL; its message quotes the URL
        raise SendError("not a valid URL")
    except Exception as e:                      # http.client.HTTPException and anything else
        raise SendError("unexpected error (%s)" % type(e).__name__)


def _teams_card(text):
    """A Teams Workflows webhook takes an Adaptive Card envelope; the classic
    connector webhooks that took {"text": ...} were retired. A TextBlock keeps
    single newlines together, so each line is its own paragraph."""
    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard", "version": "1.4",
            "body": [{"type": "TextBlock", "wrap": True,
                      "text": "\n\n".join(l for l in text.splitlines() if l.strip())}],
        }}]}


def _text(data, bullet="• "):
    """What to post: a given text (the weekly report exactly as previewed), or
    the day's standup."""
    t = data.get("_send_text")
    if t is not None:
        t = t.strip()
        if not t:
            return None
        lines = [(bullet + x[2:]) if x.startswith("\u2022 ") else x for x in t.split("\n")]
        return redact("\n".join(lines) + "\n")
    out = to_standup(data, bullet=bullet)
    return redact(out) if out else out


def payload_for(target, data):
    """(url, json payload, extra headers) for one destination's post. Pure, so
    the tests can check the exact shape each service is sent. For Linear this
    is the comment itself; `target["issue_uuid"]` must already be resolved."""
    kind = target["kind"]
    if target.get("format") == "markdown" and kind != "slack":
        t = _text(data, bullet="- ")
        if t:
            lines = t.split("\n")
            t = "\n".join(["**%s**" % lines[0]] + lines[1:])
        if kind == "teams":
            return target["url"], _teams_card(t), {}
        if kind == "linear":
            return LINEAR_API, {"query": LINEAR_MUTATION, "variables": {"input": {
                "issueId": target.get("issue_uuid", target["issue"]), "body": t}}}, {"Authorization": target["key"]}
    if kind == "slack":
        # Slack reads &, < and > as markup, so a highlight mentioning <div>
        # would vanish without this.
        text = _text(data)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return target["url"], {"text": text}, {}
    if kind == "teams":
        return target["url"], _teams_card(_text(data, bullet="- ")), {}
    if kind == "linear":
        body = {"query": LINEAR_MUTATION,
                "variables": {"input": {"issueId": target.get("issue_uuid", target["issue"]),
                                        "body": _text(data, bullet="- ")}}}
        return LINEAR_API, body, {"Authorization": target["key"]}
    raise ValueError(kind)


def _linear(payload, key):
    """One GraphQL call. Linear answers 200 even when it refuses, with the
    reason in "errors", so that is checked here, not left to the status."""
    reply = _post(LINEAR_API, payload, {"Authorization": key})
    try:
        doc = json.loads(reply)
    except ValueError:
        raise SendError("unreadable reply from Linear")
    if doc.get("errors"):
        first = doc["errors"][0] if isinstance(doc["errors"], list) and doc["errors"] else {}
        msg = str((first or {}).get("message") or "refused") if isinstance(first, dict) else "refused"
        raise SendError(msg[:80])
    return doc.get("data") or {}


def _send_one(target, data):
    if target["kind"] in ("slack", "teams") and not target["url"].startswith("https://"):
        raise SendError("the webhook must start with https")
    if target["kind"] == "linear":
        found = _linear({"query": LINEAR_ISSUE_QUERY, "variables": {"id": target["issue"]}},
                        target["key"])
        uuid = (found.get("issue") or {}).get("id")
        if not uuid:
            raise SendError("issue %s not found" % target["issue"][:40])
        target = dict(target, issue_uuid=uuid)
        _, payload, _ = payload_for(target, data)
        done = _linear(payload, target["key"])
        if not (done.get("commentCreate") or {}).get("success"):
            raise SendError("Linear did not accept the comment")
        return
    url, payload, headers = payload_for(target, data)
    _post(url, payload, headers)


def card_data(date, build):
    return apply_hide(_card_data(date, build))   # what is sent matches the preview, rules included


def _card_data(date, build):
    """The day exactly as the card shows it, without asking the claude CLI for
    anything: the cached day (cache/<date>.json, written with the card), with
    hand edits saved since then laid over it. With no cached day, a fresh build
    plus whatever summary is already cached. Never writes the polish cache."""
    data = None
    try:
        with open(os.path.join(CACHE, date + ".json")) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        pass
    fresh = data is None
    if fresh:
        data = build(date)
    if os.path.exists(app_path("polish.off")):
        return data                              # the card shows no summary then
    try:
        with open(os.path.join(CACHE, "polish-" + date + ".json")) as fh:
            c = json.load(fh)
    except (OSError, ValueError):
        return data
    hl = c.get("highlights") if isinstance(c, dict) else None
    if isinstance(hl, list) and hl and (fresh or c.get("edited")):
        data["highlights"] = [h for h in hl if isinstance(h, str) and h.strip()]
    return data


def send_day(data, targets=None):
    """Post the day to every destination in send.txt.

    Returns (sent, failed): display names that worked, and safe one-line
    reasons for those that did not. Every destination is tried even if an
    earlier one fails, so one bad webhook cannot block the others.
    """
    targets = load_send_targets() if targets is None else targets
    if not targets:
        return [], ["nothing to send to: add a destination to send.txt"]
    if data.get("_send_text") is None:
        data = apply_hide(data)
    if _text(data) is None:
        return [], ["no work recorded for this day, nothing sent"]
    sent, failed = [], []
    for t in targets:
        if t.get("kind") == "email":
            # Not sent by EOD: the app opens a draft. Printed as a mailto: line.
            from urllib.parse import quote
            body = (_text(data, bullet="- ") or "")[:1800]      # mail apps drop very long mailto: links
            subject = body.split("\n", 1)[0] if body else "Work update"
            print("MAILTO mailto:%s?subject=%s&body=%s" % (quote(t["to"], safe="@"), quote(subject), quote(body)))
            sent.append("Email draft")
            continue
        if t.get("bad"):
            failed.append("send.txt line %d not understood" % t["bad"])
            continue
        name = SEND_LABELS[t["kind"]]
        try:
            _send_one(t, data)
            sent.append(name)
        except SendError as e:
            failed.append("%s: %s" % (name, _scrub(str(e), t)))
        except Exception as e:                   # never str(e): it may quote a secret
            failed.append("%s: unexpected error (%s)" % (name, type(e).__name__))
    return sent, failed


def _scrub(msg, target):
    """Belt and braces: none of the messages above should contain a secret,
    but a reply from a service is not ours to promise about."""
    for secret in (target.get("url"), target.get("key")):
        if secret:
            msg = msg.replace(secret, "[hidden]")
    return msg
