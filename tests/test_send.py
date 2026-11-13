"""The Send button's engine half: send.txt parsing, what each service is sent,
and how failures are reported. No test here touches the network: urlopen is
replaced on every test, and the replacement fails loudly if a case forgets."""

import contextlib
import io
import json
import os
import sys
from urllib.error import HTTPError, URLError

from harness import TranscriptCase, title_line, user_line

DAY = "2026-08-06"
SLACK = "https://hooks.slack.com/services/T000/B000/SECRETslack"
TEAMS = "https://prod-00.westus.logic.azure.com:443/workflows/SECRETteams/triggers/manual/paths/invoke?sig=x"
LINEAR_KEY = "lin_api_SECRETkey"


class Reply:
    def __init__(self, body="ok"):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


class SendCase(TranscriptCase):
    def setUp(self):
        TranscriptCase.setUp(self)
        self.calls = []
        self.replies = []          # per call: a body string, or an exception to raise
        self.ex.SEND_FILE = os.path.join(self.tmp, "send.txt")

        def fake_urlopen(req, timeout=None):
            self.calls.append({
                "url": req.full_url, "method": req.get_method(),
                "headers": {k.lower(): v for k, v in req.header_items()},
                "json": json.loads(req.data.decode("utf-8")), "timeout": timeout,
            })
            r = self.replies.pop(0) if self.replies else "ok"
            if isinstance(r, Exception):
                raise r
            return Reply(r)
        self.ex.urlopen = fake_urlopen

    def configure(self, *lines):
        with open(self.ex.SEND_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(self.ex.SEND_FILE, 0o600)

    def a_day(self):
        self.write_session("-Users-me-work-alpha", "s.jsonl", [
            title_line("Fixed the rounding bug"),
            user_line("fix the rounding bug", DAY, "10:00"),
        ], mtime_date=DAY)
        data = self.ex.build(DAY)
        data["highlights"] = ["Fixed the <rounding> bug & shipped it", "Reviewed PR 501"]
        return data

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["extract.py", "--date", DAY] + list(args)
        code = 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.ex.main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()


class TestSendConfig(SendCase):
    def test_no_file_means_no_destinations(self):
        self.assertEqual(self.ex.load_send_targets(), [])
        self.assertEqual(self.ex.send_labels(), [])

    def test_lines_parse_and_comments_are_skipped(self):
        self.configure("# my channels", "", "slack " + SLACK, "TEAMS  " + TEAMS,
                       "linear %s ENG-123" % LINEAR_KEY)
        t = self.ex.load_send_targets()
        self.assertEqual([x["kind"] for x in t], ["slack", "teams", "linear"])
        self.assertEqual(t[2]["issue"], "ENG-123")
        self.assertEqual(self.ex.send_labels(), ["Slack", "Teams", "Linear"])

    def test_a_bad_line_is_reported_by_number_never_by_content(self):
        self.configure("slack " + SLACK, "linear " + LINEAR_KEY)      # issue id missing
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual(sent, ["Slack"])
        self.assertEqual(failed, ["send.txt line 2 not understood"])
        self.assertNotIn(LINEAR_KEY, " ".join(failed))


class TestPayloads(SendCase):
    def test_slack_gets_text_with_markup_escaped(self):
        self.configure("slack " + SLACK)
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual((sent, failed), (["Slack"], []))
        c, = self.calls
        self.assertEqual((c["url"], c["method"]), (SLACK, "POST"))
        self.assertEqual(c["headers"]["content-type"], "application/json")
        self.assertEqual(list(c["json"]), ["text"])
        self.assertIn("• Fixed the &lt;rounding&gt; bug &amp; shipped it", c["json"]["text"])
        self.assertTrue(c["json"]["text"].startswith("Daily update: "))
        self.assertIsNotNone(c["timeout"])

    def test_teams_gets_an_adaptive_card_for_a_workflows_webhook(self):
        self.configure("teams " + TEAMS)
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual((sent, failed), (["Teams"], []))
        c, = self.calls
        self.assertEqual(c["url"], TEAMS)
        self.assertEqual(c["json"]["type"], "message")
        att, = c["json"]["attachments"]
        self.assertEqual(att["contentType"], "application/vnd.microsoft.card.adaptive")
        card = att["content"]
        self.assertEqual((card["type"], card["version"]), ("AdaptiveCard", "1.4"))
        self.assertEqual(card["$schema"], "http://adaptivecards.io/schemas/adaptive-card.json")
        block, = card["body"]
        self.assertEqual((block["type"], block["wrap"]), ("TextBlock", True))
        # A TextBlock folds single newlines, so every line is its own paragraph.
        self.assertIn("\n\n- Fixed the <rounding> bug & shipped it\n\n- Reviewed PR 501",
                      block["text"])

    def test_linear_resolves_the_identifier_then_comments_on_the_uuid(self):
        self.configure("linear %s ENG-123" % LINEAR_KEY)
        self.replies = ['{"data": {"issue": {"id": "uuid-0001"}}}',
                        '{"data": {"commentCreate": {"success": true}}}']
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual((sent, failed), (["Linear"], []))
        look, post = self.calls
        for c in (look, post):
            self.assertEqual(c["url"], "https://api.linear.app/graphql")
            # A personal API key goes in bare, with no "Bearer".
            self.assertEqual(c["headers"]["authorization"], LINEAR_KEY)
        self.assertIn("issue(id: $id)", look["json"]["query"])
        self.assertEqual(look["json"]["variables"], {"id": "ENG-123"})
        self.assertIn("commentCreate", post["json"]["query"])
        inp = post["json"]["variables"]["input"]
        self.assertEqual(inp["issueId"], "uuid-0001")
        self.assertIn("- Fixed the <rounding> bug & shipped it", inp["body"])

    def test_linear_unknown_issue_posts_nothing(self):
        self.configure("linear %s ENG-999" % LINEAR_KEY)
        self.replies = ['{"data": {"issue": null}}']
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual(sent, [])
        self.assertEqual(failed, ["Linear: issue ENG-999 not found"])
        self.assertEqual(len(self.calls), 1)

    def test_only_work_lines_are_sent(self):
        """Screen time and browsing stay on the Mac."""
        data = self.a_day()
        data["apps"] = [{"name": "SecretApp", "secs": 600}]
        data["web"] = [{"host": "jobs.example.com", "count": 3, "start": "10:00",
                        "end": "11:00", "titles": [{"t": "10:00", "title": "Apply now"}]}]
        for kind, target in (("slack", {"kind": "slack", "url": SLACK}),
                             ("linear", {"kind": "linear", "key": LINEAR_KEY, "issue": "E-1"})):
            _, payload, _ = self.ex.payload_for(target, data)
            blob = json.dumps(payload)
            self.assertNotIn("SecretApp", blob, kind)
            self.assertNotIn("jobs.example.com", blob, kind)

    def test_without_highlights_the_project_items_are_sent(self):
        self.configure("slack " + SLACK)
        data = self.a_day()
        data["highlights"] = []
        self.ex.send_day(data)
        self.assertIn("Fixed the rounding bug", self.calls[0]["json"]["text"])


class TestFailures(SendCase):
    def test_unconfigured_sends_nothing_and_says_how_to_fix_it(self):
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual(sent, [])
        self.assertIn("send.txt", failed[0])
        self.assertEqual(self.calls, [])

    def test_a_quiet_day_sends_nothing(self):
        self.configure("slack " + SLACK)
        sent, failed = self.ex.send_day(self.ex.build(DAY))
        self.assertEqual(sent, [])
        self.assertIn("nothing sent", failed[0])
        self.assertEqual(self.calls, [])

    def test_http_error_is_reported_without_the_url_and_others_still_go(self):
        self.configure("slack " + SLACK, "teams " + TEAMS)
        self.replies = [HTTPError(SLACK, 404, "Not Found", {}, io.BytesIO(b"no_service")), "1"]
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual(sent, ["Teams"])
        self.assertEqual(failed, ["Slack: HTTP 404 no_service"])
        self.assertEqual(len(self.calls), 2)

    def test_network_error_is_reported_by_type(self):
        self.configure("teams " + TEAMS)
        self.replies = [URLError(OSError("nodename nor servname provided"))]
        _, failed = self.ex.send_day(self.a_day())
        self.assertEqual(failed, ["Teams: could not connect (OSError)"])

    def test_a_redirect_is_reported_not_followed(self):
        self.configure("slack " + SLACK)
        self.replies = [HTTPError(SLACK, 302, "Found", {}, io.BytesIO(b""))]
        _, failed = self.ex.send_day(self.a_day())
        self.assertEqual(failed, ["Slack: redirected (HTTP 302), not followed"])

    def test_the_real_opener_never_follows_redirects(self):
        # Read from eod.send itself: polish.py has its own _NoRedirect, and the
        # facade would hand back whichever module it finds first.
        send = next(m for m in self.ex._mods if m.__name__ == "eod.send")
        h = send._NoRedirect()
        self.assertIsNone(h.redirect_request(None, None, 302, "Found", {}, "https://x.example/"))
        self.assertTrue(any(isinstance(x, send._NoRedirect) for x in send._OPENER.handlers))
        self.assertFalse(any(type(x).__name__ == "HTTPRedirectHandler"
                             for x in send._OPENER.handlers))

    def test_errors_that_quote_the_url_never_leak_it(self):
        """urllib's own messages quote the URL. Whatever it raises, the secret
        must not reach the reply, and the next destination is still tried."""
        import http.client
        bad = "https://hooks.slack.com/services/SECRET\x7fctl"
        self.configure("slack " + bad, "slack " + SLACK, "teams " + TEAMS,
                       "linear %s ENG-1" % LINEAR_KEY)
        self.replies = [http.client.InvalidURL("URL can't contain control characters. %r" % bad),
                        ValueError("unknown url type: %r" % SLACK),
                        RuntimeError("boom at " + TEAMS),
                        http.client.RemoteDisconnected("closed " + LINEAR_KEY)]
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual(sent, [])
        self.assertEqual(failed, ["Slack: unexpected error (InvalidURL)",
                                  "Slack: not a valid URL",
                                  "Teams: unexpected error (RuntimeError)",
                                  "Linear: network error (RemoteDisconnected)"])
        self.assertEqual(len(self.calls), 4)
        for secret in (bad, "SECRET", SLACK, TEAMS, LINEAR_KEY):
            self.assertNotIn(secret, " ".join(failed))

    def test_an_exception_outside_post_is_caught_by_type(self):
        self.configure("slack " + SLACK, "teams " + TEAMS)
        real = self.ex.payload_for

        def boom(target, data):
            if target["kind"] == "slack":
                raise KeyError(SLACK)
            return real(target, data)
        self.ex.payload_for = boom
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual(sent, ["Teams"])
        self.assertEqual(failed, ["Slack: unexpected error (KeyError)"])

    def test_linear_refusal_inside_a_200_is_a_failure(self):
        self.configure("linear %s ENG-404" % LINEAR_KEY)
        self.replies = ['{"errors": [{"message": "Entity not found: Issue"}]}']
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual(sent, [])
        self.assertEqual(failed, ["Linear: Entity not found: Issue"])

    def test_a_reply_echoing_a_secret_is_scrubbed(self):
        self.configure("linear %s ENG-1" % LINEAR_KEY)
        self.replies = ['{"errors": [{"message": "bad key %s"}]}' % LINEAR_KEY]
        _, failed = self.ex.send_day(self.a_day())
        self.assertNotIn(LINEAR_KEY, failed[0])
        self.assertIn("[hidden]", failed[0])

    def test_plain_http_webhook_is_refused_before_any_connection(self):
        self.configure("slack http://hooks.slack.com/services/x")
        _, failed = self.ex.send_day(self.a_day())
        self.assertIn("https", failed[0])
        self.assertEqual(self.calls, [])


class TestCli(SendCase):
    @staticmethod
    def snap(path):
        with open(path) as f:
            return os.stat(path).st_mtime_ns, f.read()

    def test_send_success_prints_sent_and_exits_zero(self):
        self.a_day()
        self.configure("slack " + SLACK, "teams " + TEAMS)
        code, out, err = self.run_cli("--send")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "SENT Slack, Teams")
        self.assertEqual(len(self.calls), 2)

    def test_send_failure_exits_nonzero_and_never_prints_a_secret(self):
        self.a_day()
        self.configure("slack " + SLACK, "linear %s ENG-1" % LINEAR_KEY)
        self.replies = ["ok", HTTPError("https://api.linear.app/graphql", 401, "Unauthorized",
                                        {}, io.BytesIO(LINEAR_KEY.encode()))]
        code, out, err = self.run_cli("--send")
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), "Sent to Slack, but Linear: HTTP 401 [hidden]")
        for secret in (SLACK, LINEAR_KEY):
            self.assertNotIn(secret, out + err)

    def test_send_unconfigured_exits_nonzero(self):
        self.a_day()
        code, out, err = self.run_cli("--send")
        self.assertEqual(code, 1)
        self.assertIn("send.txt", err)
        self.assertEqual(self.calls, [])

    def test_send_does_not_rewrite_the_receipt(self):
        self.a_day()
        self.configure("slack " + SLACK)
        self.run_cli("--send")
        self.assertFalse(os.path.exists(os.path.join(self.ex.CACHE, DAY + ".html")))


    def test_send_posts_the_card_and_never_runs_the_claude_cli(self):
        """What the card shows, not a fresh summary: no claude call, no rewrite
        of the polish cache, hand edits included."""
        self.a_day()
        claude = []
        self.ex._claude_bin = lambda: "/usr/local/bin/claude"
        self.ex._run_claude = lambda *a, **k: (claude.append(1), None)[1]
        with open(os.path.join(self.ex.CACHE, DAY + ".json"), "w") as f:
            json.dump(dict(self.ex.build(DAY), highlights=["Line on the card"]), f)
        pol = os.path.join(self.ex.CACHE, "polish-%s.json" % DAY)
        with open(pol, "w") as f:
            json.dump({"key": "stale", "highlights": ["Older summary"]}, f)
        before = self.snap(pol)
        self.configure("slack " + SLACK)

        code, out, _ = self.run_cli("--send")
        self.assertEqual(code, 0)
        self.assertIn("• Line on the card", self.calls[-1]["json"]["text"])
        self.assertNotIn("Older summary", self.calls[-1]["json"]["text"])

        with open(pol, "w") as f:      # saved hand edits win, even before the card re-renders
            json.dump({"key": "edited", "highlights": ["My edited line"], "edited": True}, f)
        before = self.snap(pol)
        self.run_cli("--send")
        self.assertIn("• My edited line", self.calls[-1]["json"]["text"])
        self.assertEqual(claude, [], "--send must never run the claude CLI")
        self.assertEqual(self.snap(pol), before)

    def test_without_a_cached_card_the_cached_summary_is_used(self):
        self.a_day()
        with open(os.path.join(self.ex.CACHE, "polish-%s.json" % DAY), "w") as f:
            json.dump({"key": "k", "highlights": ["Cached summary line"]}, f)
        self.ex._run_claude = lambda *a, **k: self.fail("claude CLI called")
        self.configure("slack " + SLACK)
        self.run_cli("--send")
        self.assertIn("• Cached summary line", self.calls[0]["json"]["text"])

    def test_a_secret_in_any_exception_never_reaches_the_output(self):
        self.a_day()
        self.configure("slack " + SLACK, "linear %s ENG-1" % LINEAR_KEY)
        self.replies = [ValueError("bad " + SLACK), RuntimeError("bad " + LINEAR_KEY)]
        code, out, err = self.run_cli("--send")
        self.assertEqual(code, 1)
        for secret in (SLACK, LINEAR_KEY, "SECRET"):
            self.assertNotIn(secret, out + err)

    def test_a_readable_send_txt_draws_a_one_line_warning(self):
        self.a_day()
        self.configure("slack " + SLACK)
        os.chmod(self.ex.SEND_FILE, 0o644)
        code, out, err = self.run_cli("--send")
        self.assertEqual(code, 0)
        self.assertEqual(err, "warning: send.txt is readable by other users; chmod 600 send.txt\n")
        os.chmod(self.ex.SEND_FILE, 0o600)
        _, _, err = self.run_cli("--send")
        self.assertEqual(err, "")


class TestButton(SendCase):
    def html(self):
        with open(os.path.join(self.ex.CACHE, DAY + ".html")) as f:
            return f.read()

    def test_a_page_from_an_older_engine_is_redrawn_on_an_unchanged_day(self):
        """After an update the new design shows at once, not when the day next changes."""
        self.a_day()
        _, out, _ = self.run_cli()
        self.assertTrue(out.startswith("CHANGED"))
        _, out, _ = self.run_cli()
        self.assertTrue(out.startswith("UNCHANGED"))
        path = os.path.join(self.ex.CACHE, DAY + ".html")
        with open(path) as f:
            old = f.read().replace("<meta name='eod-render' content='", "<meta name='eod-render' content='old", 1)
        with open(path, "w") as f:
            f.write(old)
        _, out, _ = self.run_cli()
        self.assertTrue(out.startswith("CHANGED"), "an older engine's page must be redrawn")
        self.assertNotIn("content='old", self.html())

    def test_button_follows_send_txt_even_when_the_day_is_unchanged(self):
        self.a_day()
        code, out, _ = self.run_cli()
        self.assertTrue(out.startswith("CHANGED"))
        self.assertNotIn("sendBtn", self.html())
        self.assertNotIn("postUpdate", self.html())

        self.configure("slack " + SLACK)
        _, out, _ = self.run_cli()
        self.assertTrue(out.startswith("CHANGED"), "adding send.txt must reload the card")
        page = self.html()
        self.assertIn("id='sendBtn'", page)
        self.assertIn("Post the work update to Slack", page)
        self.assertNotIn(SLACK, page)

        _, out, _ = self.run_cli()
        self.assertTrue(out.startswith("UNCHANGED"))

        os.remove(self.ex.SEND_FILE)
        _, out, _ = self.run_cli()
        self.assertTrue(out.startswith("CHANGED"))
        self.assertNotIn("sendBtn", self.html())
        self.assertEqual(self.calls, [], "rendering must never post")
