import { Clipboard, showHUD } from "@raycast/api";
import { execFile } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

// EOD's engine lives in the Mac app's data folder. Nothing is sent anywhere:
// this runs it locally and puts the text on the clipboard.
const ENGINE = join(homedir(), "Library", "Application Support", "EOD", "extract.py");

export async function copyFromEod(flag: "--standup" | "--morning", done: string, empty: string) {
  const text = await new Promise<string>((resolve) => {
    execFile("/usr/bin/python3", [ENGINE, flag], { timeout: 60_000 }, (err, stdout) => resolve(err ? "" : stdout));
  });
  if (!text.trim()) {
    await showHUD(empty);
    return;
  }
  await Clipboard.copy(text);
  await showHUD(done);
}
