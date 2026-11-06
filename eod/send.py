"""Post the day's update to Slack, Teams or Linear: the receipt's Send button.

This is the one module in the engine that opens a network connection, and it is
reached only through `extract.py --send`, which eod.lua runs when you press Send.
Destinations come from send.txt (see config.load_send_targets); with no file
there is no button, and nothing here ever runs.

Webhook URLs and the Linear key are secrets. No message below includes them:
every error names the destination and what went wrong, never its address.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import SEND_LABELS, load_send_targets
from .render.text import to_standup

TIMEOUT = 15
LINEAR_API = "https://api.linear.app/graphql"
LINEAR_MUTATION = ("mutation EodComment($input: CommentCreateInput!) "
                   "{ commentCreate(input: $input) { success } }")


class SendError(Exception):
    """A failure that is safe to show: it never carries a secret."""


def _post(url, payload, headers=None):
    h = {"Content-Type": "application/json", "User-Agent": "EOD"}
    h.update(headers or {})
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST")
    try:
        with urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", "replace")
    except HTTPError as e:
        # Slack and Teams answer with a short reason ("invalid_token",
        # "no_service"), which is the useful part. Their bodies never echo the URL.
        try:
            reason = e.read().decode("utf-8", "replace").strip()
        except Exception:
            reason = ""
        finally:
            e.close()
        raise SendError("HTTP %d%s" % (e.code, (" " + reason[:60]) if reason else ""))
    except URLError as e:
        raise SendError("could not connect (%s)" % str(e.reason)[:60])
    except OSError as e:          # a timeout mid-read, a reset connection
        raise SendError("network error (%s)" % type(e).__name__)


def payload_for(target, data):
    """(url, json payload, extra headers) for one destination. Pure, so the
    tests can check the exact shape each service is sent."""
    kind = target["kind"]
    if kind == "slack":
        # Slack reads &, < and > as markup, so a highlight mentioning <div>
        # would vanish without this.
        text = to_standup(data)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return target["url"], {"text": text}, {}
    if kind == "teams":
        return target["url"], {"text": to_standup(data, bullet="- ")}, {}
    if kind == "linear":
        body = {"query": LINEAR_MUTATION,
                "variables": {"input": {"issueId": target["issue"],
                                        "body": to_standup(data, bullet="- ")}}}
        return LINEAR_API, body, {"Authorization": target["key"]}
    raise ValueError(kind)


def _send_one(target, data):
    if target["kind"] in ("slack", "teams") and not target["url"].startswith("https://"):
        raise SendError("the webhook must be an https:// URL")
    url, payload, headers = payload_for(target, data)
    reply = _post(url, payload, headers)
    if target["kind"] == "linear":
        # Linear answers 200 even when it refuses, with the reason in "errors".
        try:
            doc = json.loads(reply)
        except ValueError:
            raise SendError("unreadable reply from Linear")
        if doc.get("errors"):
            msg = str((doc["errors"][0] or {}).get("message") or "refused")
            raise SendError(msg[:80])
        if not (((doc.get("data") or {}).get("commentCreate") or {}).get("success")):
            raise SendError("Linear did not accept the comment")


def send_day(data, targets=None):
    """Post the day to every destination in send.txt.

    Returns (sent, failed): display names that worked, and safe one-line
    reasons for those that did not. Every destination is tried even if an
    earlier one fails, so one bad webhook cannot block the others.
    """
    targets = load_send_targets() if targets is None else targets
    if not targets:
        return [], ["nothing to send to: add a destination to send.txt"]
    if to_standup(data) is None:
        return [], ["no work recorded for this day, nothing sent"]
    sent, failed = [], []
    for t in targets:
        if t.get("bad"):
            failed.append("send.txt line %d not understood" % t["bad"])
            continue
        name = SEND_LABELS[t["kind"]]
        try:
            _send_one(t, data)
            sent.append(name)
        except SendError as e:
            failed.append("%s: %s" % (name, _scrub(str(e), t)))
    return sent, failed


def _scrub(msg, target):
    """Belt and braces: none of the messages above should contain a secret,
    but a reply from a service is not ours to promise about."""
    for secret in (target.get("url"), target.get("key")):
        if secret:
            msg = msg.replace(secret, "[hidden]")
    return msg
