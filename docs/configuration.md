# Configuration

Five optional files, all sitting next to `extract.py`. None of them exist by
default; create one only if you want the behaviour.

| File | What it does |
|---|---|
| **`exclude.txt`** | One project name per line. Those projects never reach the receipt. For client, NDA or job-hunt work. Copy `exclude.txt.example` to start. | <!--claim:exclude-hides-projects-->
| **`repos.txt`** | One repo path per line. Adds repos that live outside the folders scanned by default (`~/Desktop`, `~/Documents`, `~/code`, `~/dev`, `~/projects`, `~/work`, `~/repos`). Lines starting with `#` are ignored. | <!--claim:repos-txt-read-->
| **`polish.off`** | Create this empty file to switch the optional AI-polish step off completely. EOD then never shells out to the `claude` CLI and stays fully offline. The file's contents are ignored; only its presence matters. | <!--claim:polish-off-disables-->
| **`signature.txt`** | The small mark at the foot of the receipt. Defaults to the initials of your `git config --global user.name`. Put anything you like in here to override it, or leave the file empty to print no mark at all. | <!--claim:signature-is-yours-->
| **`send.txt`** | Where the receipt's **↗ Send** button posts the day's WORK lines. One destination per line: `slack <incoming webhook URL>`, `teams <Workflows webhook URL>` (a Teams Workflows "post to a channel when a webhook request is received" URL; the old connector webhooks are retired), or `linear <personal API key> <issue>` where the issue is its identifier (`ENG-123`) or UUID, posted as a comment on it. OAuth tokens are not supported. Every listed destination gets the update. No file, no button. It holds secrets, so it is gitignored; keep it that way. | <!--claim:send-txt-button-->

```sh
cp exclude.txt.example exclude.txt   # then edit
echo ~/src/some-repo > repos.txt     # extra git repo outside the default roots
touch polish.off                     # fully offline, no claude CLI call ever
printf 'AG' > signature.txt          # override the footer mark (empty file = none)
printf 'slack https://hooks.slack.com/services/...\n' > send.txt   # adds the Send button
```
