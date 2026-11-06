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
TEAMS = "https://example.webhook.office.com/webhookb2/SECRETteams"
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

    def test_teams_gets_a_markdown_list(self):
        self.configure("teams " + TEAMS)
        self.ex.send_day(self.a_day())
        c, = self.calls
        self.assertEqual(c["url"], TEAMS)
        self.assertEqual(list(c["json"]), ["text"])
        self.assertIn("\n- Reviewed PR 501", c["json"]["text"])

    def test_linear_gets_a_comment_create_mutation(self):
        self.configure("linear %s ENG-123" % LINEAR_KEY)
        self.replies = ['{"data": {"commentCreate": {"success": true}}}']
        sent, failed = self.ex.send_day(self.a_day())
        self.assertEqual((sent, failed), (["Linear"], []))
        c, = self.calls
        self.assertEqual(c["url"], "https://api.linear.app/graphql")
        self.assertEqual(c["headers"]["authorization"], LINEAR_KEY)
        self.assertIn("commentCreate", c["json"]["query"])
        inp = c["json"]["variables"]["input"]
        self.assertEqual(inp["issueId"], "ENG-123")
        self.assertIn("- Fixed the <rounding> bug & shipped it", inp["body"])

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

    def test_network_error_is_reported(self):
        self.configure("teams " + TEAMS)
        self.replies = [URLError("nodename nor servname provided")]
        _, failed = self.ex.send_day(self.a_day())
        self.assertEqual(failed, ["Teams: could not connect (nodename nor servname provided)"])

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
        self.assertIn("https://", failed[0])
        self.assertEqual(self.calls, [])


class TestCli(SendCase):
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
        self.replies = ["ok", HTTPError(LINEAR_KEY, 401, "Unauthorized", {}, io.BytesIO(b""))]
        code, out, err = self.run_cli("--send")
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), "Sent to Slack, but Linear: HTTP 401")
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


class TestButton(SendCase):
    def html(self):
        with open(os.path.join(self.ex.CACHE, DAY + ".html")) as f:
            return f.read()

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
