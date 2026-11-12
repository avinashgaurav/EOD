import { copyFromEod } from "./run";

export default async function Command() {
  await copyFromEod("--morning", "Standup copied", "Nothing for a standup yet");
}
