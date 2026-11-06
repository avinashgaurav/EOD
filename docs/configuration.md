# Configuration

Five optional files, all sitting next to `extract.py`. None of them exist by
default; create one only if you want the behaviour.

| File | What it does |
|---|---|
| **`exclude.txt`** | One project name per line. Those projects never reach the receipt. For client, NDA or job-hunt work. Copy `exclude.txt.example` to start. | <!--claim:exclude-hides-projects-->
| **`repos.txt`** | One repo path per line. Adds repos that live outside the folders scanned by default (`~/Desktop`, `~/Documents`, `~/code`, `~/dev`, `~/projects`, `~/work`, `~/repos`). Lines starting with `#` are ignored. | <!--claim:repos-txt-read-->
| **`polish.off`** | Create this empty file to switch the optional AI-polish step off completely. EOD then never calls the `claude` CLI or Ollama and stays fully offline. The file's contents are ignored; only its presence matters. | <!--claim:polish-off-disables-->
| **`ollama.txt`** | Create this file to run AI-polish on a local [Ollama](https://ollama.com) model instead of the `claude` CLI, so the summary never leaves your Mac. The first line that is not blank or a `#` comment names the model (`ollama pull` it first); otherwise `llama3.2`. Switching model or provider re-summarises on the next run. EOD only ever talks to Ollama on `127.0.0.1:11434`. If Ollama is not running or the model is missing, the receipt falls back exactly as it does when the CLI fails, and the reason goes to `cache/polish-error.log`. Delete the file to go back to `claude`. | <!--claim:ollama-stays-local-->
| **`signature.txt`** | The small mark at the foot of the receipt. Defaults to the initials of your `git config --global user.name`. Put anything you like in here to override it, or leave the file empty to print no mark at all. | <!--claim:signature-is-yours-->

```sh
cp exclude.txt.example exclude.txt   # then edit
echo ~/src/some-repo > repos.txt     # extra git repo outside the default roots
touch polish.off                     # fully offline, no claude CLI call ever
echo qwen2.5:7b > ollama.txt         # polish on local Ollama instead (empty file = llama3.2)
printf 'AG' > signature.txt          # override the footer mark (empty file = none)
```
